"""
AlphaForge — Regression tests for MAX mode Telegram handler.

All external calls are mocked:
  - requests.post  (Anthropic API + Telegram)
  - yfinance.Ticker
  - DynamoDB / boto3
  - CNN Fear & Greed (requests.get)
  - SSM Parameter Store
"""
import json
import sys
import os
from typing import Any
from unittest.mock import MagicMock, patch, call

import pytest

# ── Make the telegram handler importable without real AWS/SSM ─────────────────
# The module imports boto3 at the top level; we need to stub SSM before import.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lambdas", "telegram"))


# ── Helpers ───────────────────────────────────────────────────────────────────

class MockResponse:
    """Minimal requests.Response stub."""

    def __init__(self, status_code: int = 200, body: dict | str | None = None):
        self.status_code = status_code
        if isinstance(body, dict):
            self._body = body
            self.text = json.dumps(body)
        elif isinstance(body, str):
            self._body = None
            self.text = body
        else:
            self._body = {}
            self.text = "{}"
        self.ok = (200 <= status_code < 300)

    def json(self) -> dict:
        if self._body is not None:
            return self._body
        return json.loads(self.text)

    def raise_for_status(self):
        if not self.ok:
            from requests.exceptions import HTTPError
            raise HTTPError(f"{self.status_code} Client Error", response=self)


def _anthropic_response(content_text: str, stop_reason: str = "end_turn") -> dict:
    """Build a minimal Anthropic messages API response dict."""
    return {
        "content": [{"type": "text", "text": content_text}],
        "stop_reason": stop_reason,
        "model": "claude-sonnet-4-6",
    }


def _haiku_json_text() -> str:
    """Normal-mode Buffett Haiku JSON (without the leading '{' — prefill adds it)."""
    return json.dumps({
        "verdict": "BULLISH",
        "moat": "WIDE",
        "valuation": "FAIR",
        "one_liner": "AMZN มีความได้เปรียบสูง",
        "key_concern": None,
    })[1:]  # strip leading '{' — handler re-attaches it via prefill


def _sonnet_buffett_json_text() -> str:
    """MAX-mode Buffett Sonnet JSON (without leading '{')."""
    return json.dumps({
        "verdict": "BULLISH",
        "moat": "WIDE",
        "valuation": "FAIR",
        "moat_analysis": "AMZN มี network effects แข็งแกร่ง ROE 25% สูงกว่า threshold",
        "fundamental_verdict": "ผ่าน 6/8 criteria ROE และ margin แข็งแกร่ง D/E ต่ำ",
        "valuation_verdict": "P/E 40x สูงแต่ FCF yield ที่ 3% ยังสมเหตุสมผล",
        "action": "Buffett จะซื้อสะสมในระยะยาว รอ pullback 10-15% ก่อน",
        "key_concern": "ตลาด cloud แข่งขันสูงจาก Azure และ GCP",
    })[1:]


def _sonnet_dalio_json_text() -> str:
    """MAX-mode Dalio Sonnet JSON (without leading '{')."""
    return json.dumps({
        "regime": "RISK_ON",
        "cycle": "MID_EXPANSION",
        "season": "B_GROWTH_DISINFLATION",
        "cycle_analysis": "อยู่กลาง short-term cycle D/E ต่ำหมายถึงความแข็งแกร่ง",
        "sector_positioning": "Tech sector อยู่ใน sweet spot ของ B season เติบโตดี",
        "portfolio_action": "All-Weather ควรถือ 5-8% trigger คือ yield inversion",
        "macro_take": "Macro เอื้อต่อ Tech ในช่วงนี้",
        "key_risk": "Trade war อาจกดดัน margin",
    })[1:]


def _make_yf_ticker_mock(symbol: str = "AMZN") -> MagicMock:
    """Return a mock yfinance.Ticker with minimal but sufficient data."""
    import pandas as pd
    import numpy as np

    mock_ticker = MagicMock()
    # 60 bars of synthetic OHLCV
    n = 60
    np.random.seed(99)
    prices = 150.0 + np.cumsum(np.random.normal(0.2, 1.0, n))
    prices = np.abs(prices)
    idx = pd.date_range("2024-01-01", periods=n, freq="B")
    mock_ticker.history.return_value = pd.DataFrame({
        "Open": prices,
        "High": prices * 1.01,
        "Low": prices * 0.99,
        "Close": prices,
        "Volume": np.random.randint(1_000_000, 5_000_000, n),
    }, index=idx)
    mock_ticker.info = {
        "shortName": "Amazon.com Inc.",
        "sector": "Consumer Cyclical",
        "industry": "Internet Retail",
        "returnOnEquity": 0.25,
        "debtToEquity": 45.0,
        "operatingMargins": 0.07,
        "profitMargins": 0.06,
        "currentRatio": 1.05,
        "trailingPE": 40.0,
        "priceToBook": 8.5,
        "pegRatio": 1.8,
        "revenueGrowth": 0.12,
        "earningsGrowth": 0.20,
        "freeCashflow": 38_000_000_000,
        "beta": 1.2,
        "marketCap": 1_800_000_000_000,
        "country": "United States",
    }
    return mock_ticker


def _mock_ssm_get_parameter(Name: str, **kwargs) -> dict:
    """Return dummy secrets so handler can boot without real SSM."""
    return {"Parameter": {"Value": "dummy-secret"}}


def _mock_dynamo_resource():
    """Return a mock DynamoDB resource that always succeeds."""
    mock_resource = MagicMock()
    mock_table = MagicMock()
    mock_resource.Table.return_value = mock_table
    mock_table.put_item.return_value = {}
    mock_table.query.return_value = {"Items": []}
    return mock_resource


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def _reset_handler_globals():
    """Reset module-level caches between tests to avoid state bleed."""
    import importlib
    import lambdas.telegram.handler as h  # type: ignore[import]
    h._API_KEY = None
    h._SSM_CLIENT = None
    h._DYNAMO = None
    h._DYNAMO_TABLE_NAME = None
    yield
    h._API_KEY = None
    h._SSM_CLIENT = None
    h._DYNAMO = None
    h._DYNAMO_TABLE_NAME = None


# ── Test helpers ─────────────────────────────────────────────────────────────

def _patch_all(
    anthropic_side_effect: Any = None,
    anthropic_return: Any = None,
):
    """
    Return context managers that patch all external I/O used by handler.py.

    Either anthropic_side_effect OR anthropic_return must be provided.
    """
    patches = []

    # SSM
    mock_ssm_client = MagicMock()
    mock_ssm_client.get_parameter.side_effect = _mock_ssm_get_parameter
    patches.append(patch("boto3.client", return_value=mock_ssm_client))

    # DynamoDB
    patches.append(patch("boto3.resource", return_value=_mock_dynamo_resource()))

    # yfinance
    patches.append(patch("yfinance.Ticker", return_value=_make_yf_ticker_mock()))

    # CNN Fear & Greed
    fg_response = MockResponse(200, {
        "fear_and_greed": {"score": 55, "rating": "Neutral"},
    })
    patches.append(patch("requests.get", return_value=fg_response))

    # Anthropic (requests.post)
    if anthropic_side_effect is not None:
        patches.append(patch("requests.post", side_effect=anthropic_side_effect))
    elif anthropic_return is not None:
        patches.append(patch("requests.post", return_value=anthropic_return))
    else:
        raise ValueError("Provide anthropic_side_effect or anthropic_return")

    return patches


# ═════════════════════════════════════════════════════════════════════════════
# TEST a) Normal mode returns one_liner (existing behavior)
# ═════════════════════════════════════════════════════════════════════════════

class TestNormalMode:
    def test_normal_buffett_returns_one_liner(self):
        """Normal mode: Haiku returns one_liner, degraded=False, ok=True."""
        # requests.post is used for both Anthropic and Telegram sends.
        # Anthropic calls are JSON; Telegram calls have no JSON assertion here.
        call_count = [0]

        def post_side_effect(url, **kwargs):
            if "anthropic" in url:
                call_count[0] += 1
                # Both Buffett and Dalio calls share this mock
                if call_count[0] == 1:
                    # Buffett call
                    body = _anthropic_response(_haiku_json_text())
                    return MockResponse(200, body)
                else:
                    # Dalio call
                    dalio_text = json.dumps({
                        "regime": "RISK_ON",
                        "cycle": "MID_EXPANSION",
                        "season": "B_GROWTH_DISINFLATION",
                        "macro_take": "ตลาดดี",
                        "key_risk": "ความเสี่ยงดอกเบี้ย",
                    })[1:]
                    body = _anthropic_response(dalio_text)
                    return MockResponse(200, body)
            # Telegram send
            return MockResponse(200, {"ok": True})

        with patch("boto3.client") as mock_boto3_client, \
             patch("boto3.resource", return_value=_mock_dynamo_resource()), \
             patch("yfinance.Ticker", return_value=_make_yf_ticker_mock()), \
             patch("requests.get", return_value=MockResponse(200, {"fear_and_greed": {"score": 55, "rating": "Neutral"}})), \
             patch("requests.post", side_effect=post_side_effect):

            mock_ssm_client = MagicMock()
            mock_ssm_client.get_parameter.side_effect = _mock_ssm_get_parameter
            mock_boto3_client.return_value = mock_ssm_client

            import lambdas.telegram.handler as h  # type: ignore[import]
            result = h._get_buffett_take("AMZN", "Amazon.com Inc.", {
                "returnOnEquity": 0.25, "debtToEquity": 45.0, "operatingMargins": 0.07,
                "profitMargins": 0.06, "currentRatio": 1.05, "trailingPE": 40.0,
                "revenueGrowth": 0.12, "earningsGrowth": 0.20, "freeCashflow": 38_000_000_000,
                "sector": "Consumer Cyclical", "industry": "Internet Retail",
            }, max_mode=False)

        assert result["one_liner"], "one_liner should be non-empty"
        assert result["degraded"] is False, "normal mode should not be degraded"
        assert result["ok"] is True, "normal mode should be ok"
        assert result["verdict"] == "BULLISH"


# ═════════════════════════════════════════════════════════════════════════════
# TEST b) MAX mode returns detailed fields on success
# ═════════════════════════════════════════════════════════════════════════════

class TestMaxModeSuccess:
    def test_buffett_max_returns_detailed_fields(self):
        """MAX mode: Sonnet returns all 4 detailed fields, degraded=False, ok=True."""
        body = _anthropic_response(_sonnet_buffett_json_text())

        with patch("boto3.client") as mock_boto3_client, \
             patch("requests.post", return_value=MockResponse(200, body)):

            mock_ssm_client = MagicMock()
            mock_ssm_client.get_parameter.side_effect = _mock_ssm_get_parameter
            mock_boto3_client.return_value = mock_ssm_client

            import lambdas.telegram.handler as h  # type: ignore[import]
            result = h._get_buffett_take("AMZN", "Amazon.com Inc.", {
                "returnOnEquity": 0.25, "debtToEquity": 45.0, "operatingMargins": 0.07,
                "profitMargins": 0.06, "currentRatio": 1.05, "trailingPE": 40.0,
                "revenueGrowth": 0.12, "sector": "Consumer Cyclical", "industry": "Internet Retail",
            }, max_mode=True)

        assert result["moat_analysis"], "moat_analysis should be non-empty"
        assert result["fundamental_verdict"], "fundamental_verdict should be non-empty"
        assert result["valuation_verdict"], "valuation_verdict should be non-empty"
        assert result["action"], "action should be non-empty"
        assert result["degraded"] is False
        assert result["ok"] is True

    def test_dalio_max_returns_detailed_fields(self):
        """MAX mode: Dalio Sonnet returns all 3 detailed fields, degraded=False, ok=True."""
        body = _anthropic_response(_sonnet_dalio_json_text())

        with patch("boto3.client") as mock_boto3_client, \
             patch("requests.post", return_value=MockResponse(200, body)):

            mock_ssm_client = MagicMock()
            mock_ssm_client.get_parameter.side_effect = _mock_ssm_get_parameter
            mock_boto3_client.return_value = mock_ssm_client

            import lambdas.telegram.handler as h  # type: ignore[import]
            result = h._get_dalio_take("AMZN", "Amazon.com Inc.", {
                "sector": "Consumer Cyclical", "industry": "Internet Retail",
                "debtToEquity": 45.0, "trailingPE": 40.0, "beta": 1.2,
                "revenueGrowth": 0.12, "marketCap": 1_800_000_000_000,
            }, max_mode=True)

        assert result["cycle_analysis"], "cycle_analysis should be non-empty"
        assert result["sector_positioning"], "sector_positioning should be non-empty"
        assert result["portfolio_action"], "portfolio_action should be non-empty"
        assert result["degraded"] is False
        assert result["ok"] is True


# ═════════════════════════════════════════════════════════════════════════════
# TEST c) MAX mode 400 Bad Request → degraded, not fake neutral
# ═════════════════════════════════════════════════════════════════════════════

class TestMaxMode400:
    def test_buffett_400_returns_degraded(self):
        """MAX mode 400 → degraded=True, ok=False, error_reason non-empty."""
        err_body = '{"error":{"type":"invalid_request_error","message":"prompt_too_long"}}'

        with patch("boto3.client") as mock_boto3_client, \
             patch("requests.post", return_value=MockResponse(400, err_body)):

            mock_ssm_client = MagicMock()
            mock_ssm_client.get_parameter.side_effect = _mock_ssm_get_parameter
            mock_boto3_client.return_value = mock_ssm_client

            import lambdas.telegram.handler as h  # type: ignore[import]
            result = h._get_buffett_take("AMZN", "Amazon.com Inc.", {}, max_mode=True)

        assert result["degraded"] is True, "400 error must set degraded=True"
        assert result["ok"] is False, "400 error must set ok=False"
        assert result["error_reason"], "error_reason must not be empty"

    def test_buffett_400_format_shows_degraded_label(self):
        """_format() with degraded buffett in MAX mode must contain 'DEGRADED'."""
        import lambdas.telegram.handler as h  # type: ignore[import]

        fake_r = {
            "symbol": "AMZN",
            "company": "Amazon.com Inc.",
            "price": 180.0,
            "change_pct": 1.5,
            "score": 0.600,
            "signal": "BUY",
            "rsi": 55.0,
            "kama_val": 178.0,
            "kama_bull": True,
            "macd_bull": True,
            "vwap": 179.0,
            "vwap_above": True,
            "vol_ratio": 1.3,
            "cmf_val": 0.1,
            "cmf_positive": True,
            "sqz_on": False,
            "sqz_pos": True,
            "max_mode": True,
            "buffett": {
                "verdict": "NEUTRAL",
                "moat": "UNKNOWN",
                "valuation": "UNKNOWN",
                "degraded": True,
                "ok": False,
                "error_reason": "400 Bad Request: invalid_request_error",
                "max_mode": True,
                "moat_analysis": "",
                "fundamental_verdict": "",
                "valuation_verdict": "",
                "action": "",
                "key_concern": None,
            },
            "dalio": {
                "regime": "RISK_ON",
                "cycle": "MID_EXPANSION",
                "season": "B_GROWTH_DISINFLATION",
                "macro_take": "ตลาดดี",
                "key_risk": None,
                "degraded": False,
                "ok": True,
                "max_mode": True,
                "cycle_analysis": "วิเคราะห์วัฏจักร",
                "sector_positioning": "Tech ดี",
                "portfolio_action": "ถือ 5%",
            },
            "fear_greed": {"value": 55, "rating": "Neutral", "emoji": "😐", "advice": "", "ok": True},
        }
        parts = h._format(fake_r)
        combined = "\n".join(parts)
        assert "DEGRADED" in combined.upper(), (
            f"Expected 'DEGRADED' in output, got:\n{combined[:500]}"
        )

    def test_dalio_400_returns_degraded(self):
        """MAX mode 400 on Dalio → degraded=True, ok=False."""
        err_body = '{"error":{"type":"invalid_request_error"}}'

        with patch("boto3.client") as mock_boto3_client, \
             patch("requests.post", return_value=MockResponse(400, err_body)):

            mock_ssm_client = MagicMock()
            mock_ssm_client.get_parameter.side_effect = _mock_ssm_get_parameter
            mock_boto3_client.return_value = mock_ssm_client

            import lambdas.telegram.handler as h  # type: ignore[import]
            result = h._get_dalio_take("AMZN", "Amazon.com Inc.", {}, max_mode=True)

        assert result["degraded"] is True
        assert result["ok"] is False
        assert result["error_reason"]


# ═════════════════════════════════════════════════════════════════════════════
# TEST d) MAX mode truncated JSON (stop_reason=max_tokens) → retry with compact schema
# ═════════════════════════════════════════════════════════════════════════════

class TestMaxModeRetry:
    def test_buffett_max_tokens_retry_succeeds(self):
        """stop_reason=max_tokens → retry with compact schema → result not degraded."""
        call_count = [0]

        def post_side_effect(url, **kwargs):
            if "anthropic" not in url:
                return MockResponse(200, {"ok": True})
            call_count[0] += 1
            if call_count[0] == 1:
                # First call: truncated JSON
                truncated = '{"verdict": "BULLISH", "moat": "WIDE", "valuation": "FAIR"'
                # Note: no closing brace — intentionally truncated
                body = _anthropic_response(truncated, stop_reason="max_tokens")
                return MockResponse(200, body)
            else:
                # Second call (retry): valid compact JSON
                compact = json.dumps({
                    "verdict": "BULLISH",
                    "moat": "WIDE",
                    "valuation": "FAIR",
                    "one_liner": "ธุรกิจดี",
                    "key_concern": None,
                })[1:]
                body = _anthropic_response(compact, stop_reason="end_turn")
                return MockResponse(200, body)

        with patch("boto3.client") as mock_boto3_client, \
             patch("requests.post", side_effect=post_side_effect):

            mock_ssm_client = MagicMock()
            mock_ssm_client.get_parameter.side_effect = _mock_ssm_get_parameter
            mock_boto3_client.return_value = mock_ssm_client

            import lambdas.telegram.handler as h  # type: ignore[import]
            result = h._get_buffett_take("AMZN", "Amazon.com Inc.", {
                "returnOnEquity": 0.25, "sector": "Technology", "industry": "Software",
            }, max_mode=True)

        assert result["degraded"] is False, (
            f"After successful retry, degraded must be False. Got: {result}"
        )
        assert result["ok"] is True

    def test_dalio_max_tokens_retry_succeeds(self):
        """Dalio stop_reason=max_tokens → retry → not degraded."""
        call_count = [0]

        def post_side_effect(url, **kwargs):
            if "anthropic" not in url:
                return MockResponse(200, {"ok": True})
            call_count[0] += 1
            if call_count[0] == 1:
                truncated = '{"regime": "RISK_ON", "cycle": "MID_EXPANSION"'
                body = _anthropic_response(truncated, stop_reason="max_tokens")
                return MockResponse(200, body)
            else:
                compact = json.dumps({
                    "regime": "RISK_ON",
                    "cycle": "MID_EXPANSION",
                    "season": "B_GROWTH_DISINFLATION",
                    "macro_take": "ตลาดดี",
                    "key_risk": None,
                })[1:]
                body = _anthropic_response(compact, stop_reason="end_turn")
                return MockResponse(200, body)

        with patch("boto3.client") as mock_boto3_client, \
             patch("requests.post", side_effect=post_side_effect):

            mock_ssm_client = MagicMock()
            mock_ssm_client.get_parameter.side_effect = _mock_ssm_get_parameter
            mock_boto3_client.return_value = mock_ssm_client

            import lambdas.telegram.handler as h  # type: ignore[import]
            result = h._get_dalio_take("AMZN", "Amazon.com Inc.", {
                "sector": "Technology", "debtToEquity": 20.0,
            }, max_mode=True)

        assert result["degraded"] is False
        assert result["ok"] is True


# ═════════════════════════════════════════════════════════════════════════════
# TEST e) MAX mode Dalio 400 → degraded Dalio, Buffett still shows
# ═════════════════════════════════════════════════════════════════════════════

class TestMaxModePartialDegradation:
    def test_buffett_ok_dalio_degraded(self):
        """Buffett succeeds, Dalio 400 → Buffett ok, Dalio degraded."""
        buffett_call = [0]
        dalio_call = [0]

        def post_side_effect(url, **kwargs):
            if "anthropic" not in url:
                return MockResponse(200, {"ok": True})
            # We distinguish Buffett vs Dalio by inspecting the system prompt
            payload = kwargs.get("json", {})
            system_text = payload.get("system", "")
            if "Warren Buffett" in system_text:
                buffett_call[0] += 1
                body = _anthropic_response(_sonnet_buffett_json_text())
                return MockResponse(200, body)
            else:
                # Dalio → 400
                dalio_call[0] += 1
                err = '{"error":{"type":"invalid_request_error"}}'
                return MockResponse(400, err)

        with patch("boto3.client") as mock_boto3_client, \
             patch("requests.post", side_effect=post_side_effect):

            mock_ssm_client = MagicMock()
            mock_ssm_client.get_parameter.side_effect = _mock_ssm_get_parameter
            mock_boto3_client.return_value = mock_ssm_client

            import lambdas.telegram.handler as h  # type: ignore[import]
            info = {
                "returnOnEquity": 0.25, "debtToEquity": 45.0, "operatingMargins": 0.07,
                "profitMargins": 0.06, "currentRatio": 1.05, "trailingPE": 40.0,
                "revenueGrowth": 0.12, "sector": "Consumer Cyclical", "industry": "Internet Retail",
                "beta": 1.2, "marketCap": 1_800_000_000_000,
            }
            b_result = h._get_buffett_take("AMZN", "Amazon.com Inc.", info, max_mode=True)
            d_result = h._get_dalio_take("AMZN", "Amazon.com Inc.", info, max_mode=True)

        # Buffett should be healthy
        assert b_result["ok"] is True
        assert b_result["degraded"] is False
        assert b_result["moat_analysis"], "Buffett moat_analysis should be populated"

        # Dalio should be degraded
        assert d_result["ok"] is False
        assert d_result["degraded"] is True
        assert d_result["error_reason"]


# ═════════════════════════════════════════════════════════════════════════════
# TEST f) Rendering: _format() with degraded MAX shows "MAX DEGRADED" label
# ═════════════════════════════════════════════════════════════════════════════

class TestFormatDegraded:
    def test_format_degraded_buffett_contains_degraded_text(self):
        """Build fake r dict with degraded buffett, assert _format() shows DEGRADED."""
        import lambdas.telegram.handler as h  # type: ignore[import]

        r = {
            "symbol": "AMZN",
            "company": "Amazon.com Inc.",
            "price": 180.0,
            "change_pct": 1.5,
            "score": 0.600,
            "signal": "BUY",
            "rsi": 55.0,
            "kama_val": 178.0,
            "kama_bull": True,
            "macd_bull": True,
            "vwap": 179.0,
            "vwap_above": True,
            "vol_ratio": 1.3,
            "cmf_val": 0.1,
            "cmf_positive": True,
            "sqz_on": False,
            "sqz_pos": True,
            "max_mode": True,
            "buffett": {
                "verdict": "NEUTRAL",
                "moat": "UNKNOWN",
                "valuation": "UNKNOWN",
                "degraded": True,
                "ok": False,
                "error_reason": "400 Bad Request",
                "max_mode": True,
                "moat_analysis": "",
                "fundamental_verdict": "",
                "valuation_verdict": "",
                "action": "",
                "key_concern": None,
            },
            "dalio": {
                "regime": "RISK_OFF",
                "cycle": "CONTRACTION",
                "season": "D_DEFLATION",
                "macro_take": "",
                "key_risk": None,
                "degraded": True,
                "ok": False,
                "error_reason": "400 Bad Request",
                "max_mode": True,
                "cycle_analysis": "",
                "sector_positioning": "",
                "portfolio_action": "",
            },
            "fear_greed": {"value": 30, "rating": "Fear", "emoji": "😨", "advice": "ระวัง", "ok": True},
        }

        parts = h._format(r)
        combined = "\n".join(parts)
        assert "DEGRADED" in combined.upper(), (
            f"Expected 'DEGRADED' in _format() output.\nGot:\n{combined[:600]}"
        )

    def test_format_degraded_max_badge_in_tech_dashboard(self):
        """Tech dashboard (part 1) should show MAX mode indicator even when degraded."""
        import lambdas.telegram.handler as h  # type: ignore[import]

        r = {
            "symbol": "AMZN",
            "company": "Amazon.com Inc.",
            "price": 180.0,
            "change_pct": -0.5,
            "score": 0.400,
            "signal": "WATCH",
            "rsi": 48.0,
            "kama_val": 182.0,
            "kama_bull": False,
            "macd_bull": False,
            "vwap": 181.0,
            "vwap_above": False,
            "vol_ratio": 0.9,
            "cmf_val": -0.1,
            "cmf_positive": False,
            "sqz_on": True,
            "sqz_pos": False,
            "max_mode": True,
            "buffett": {
                "verdict": "NEUTRAL", "moat": "UNKNOWN", "valuation": "UNKNOWN",
                "degraded": True, "ok": False, "error_reason": "400",
                "max_mode": True, "moat_analysis": "", "fundamental_verdict": "",
                "valuation_verdict": "", "action": "", "key_concern": None,
            },
            "dalio": {
                "regime": "RISK_OFF", "cycle": "CONTRACTION", "season": "D_DEFLATION",
                "macro_take": "", "key_risk": None,
                "degraded": False, "ok": True, "max_mode": True,
                "cycle_analysis": "วัฏจักร", "sector_positioning": "Tech", "portfolio_action": "ถือ",
            },
            "fear_greed": {"value": 40, "rating": "Fear", "emoji": "😨", "advice": "", "ok": True},
        }

        parts = h._format(r)
        assert len(parts) == 2, "MAX mode should return 2 message parts"
        tech_dash = parts[0]
        assert "MAX" in tech_dash.upper(), "Tech dashboard should show MAX badge"


# ═════════════════════════════════════════════════════════════════════════════
# TEST: ok/degraded fields present on normal mode success too
# ═════════════════════════════════════════════════════════════════════════════

class TestOkDegradedFields:
    def test_buffett_normal_has_ok_degraded_fields(self):
        """Normal Buffett success must have ok=True, degraded=False, model field."""
        body = _anthropic_response(_haiku_json_text())

        with patch("boto3.client") as mock_boto3_client, \
             patch("requests.post", return_value=MockResponse(200, body)):

            mock_ssm_client = MagicMock()
            mock_ssm_client.get_parameter.side_effect = _mock_ssm_get_parameter
            mock_boto3_client.return_value = mock_ssm_client

            import lambdas.telegram.handler as h  # type: ignore[import]
            result = h._get_buffett_take("AAPL", "Apple Inc.", {
                "returnOnEquity": 0.30, "sector": "Technology", "industry": "Consumer Electronics",
            }, max_mode=False)

        assert "ok" in result, "ok field must exist"
        assert "degraded" in result, "degraded field must exist"
        assert "model" in result, "model field must exist"
        assert result["ok"] is True
        assert result["degraded"] is False

    def test_dalio_normal_has_ok_degraded_fields(self):
        """Normal Dalio success must have ok=True, degraded=False, stop_reason field."""
        dalio_text = json.dumps({
            "regime": "RISK_ON",
            "cycle": "MID_EXPANSION",
            "season": "B_GROWTH_DISINFLATION",
            "macro_take": "ตลาดดี",
            "key_risk": None,
        })[1:]
        body = _anthropic_response(dalio_text)

        with patch("boto3.client") as mock_boto3_client, \
             patch("requests.post", return_value=MockResponse(200, body)):

            mock_ssm_client = MagicMock()
            mock_ssm_client.get_parameter.side_effect = _mock_ssm_get_parameter
            mock_boto3_client.return_value = mock_ssm_client

            import lambdas.telegram.handler as h  # type: ignore[import]
            result = h._get_dalio_take("AAPL", "Apple Inc.", {
                "sector": "Technology", "industry": "Consumer Electronics",
            }, max_mode=False)

        assert result["ok"] is True
        assert result["degraded"] is False
        assert "stop_reason" in result

    def test_buffett_exception_has_degraded_true(self):
        """If Buffett request raises an exception, degraded=True, ok=False."""
        from requests.exceptions import ConnectionError

        with patch("boto3.client") as mock_boto3_client, \
             patch("requests.post", side_effect=ConnectionError("Network error")):

            mock_ssm_client = MagicMock()
            mock_ssm_client.get_parameter.side_effect = _mock_ssm_get_parameter
            mock_boto3_client.return_value = mock_ssm_client

            import lambdas.telegram.handler as h  # type: ignore[import]
            result = h._get_buffett_take("AMZN", "Amazon.com Inc.", {}, max_mode=True)

        assert result["degraded"] is True
        assert result["ok"] is False
        assert result["error_reason"]
        assert "Network error" in result["error_reason"]
