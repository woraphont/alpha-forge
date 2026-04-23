"""
AlphaForge — Tests for the scoring engine (Phase 2).
Run: pytest tests/test_scorer.py -v

Rules:
  - ALL network / AWS / API calls are mocked — tests are fully offline/deterministic.
  - Phase 2 keys expected: fear_greed, dalio_score, phase=="PHASE_2_FG_RS"
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../lambdas/analyzer"))

from unittest.mock import patch

import pytest
from conftest import make_ohlcv
from scorer import calculate_score


# ── shared Phase 2 mock payload ──────────────────────────────────────────────
_MOCK_AI_SCORES = {
    "finbert": 0.6,
    "fear_greed": 0.4,
    "llm_pattern": 0.6,
    "finbert_label": "positive",
    "finbert_source": "mock",
    "fg_value": 45,
    "fg_rating": "Neutral",
    "llm_signal": "BUY",
    "llm_moat": "WIDE",
    "llm_valuation": "FAIR",
    "llm_reasoning": "test",
    "llm_key_concern": None,
    "dalio_score": 0.5,
    "dalio_regime": "RISK_ON",
    "dalio_cycle": "MID_EXPANSION",
    "dalio_season": "B_GROWTH_DISINFLATION",
    "dalio_big_cycle": None,
    "dalio_bias": "neutral",
    "dalio_key_risk": None,
    "phase": "PHASE_2_FG_RS",
    "ai_disabled": False,
}


def _patched_score(symbol, df, news, fundamentals=None, spy_df=None):
    """Helper: run calculate_score with AI layer fully mocked (no network calls)."""
    with patch("scorer._get_ai_scores", return_value=_MOCK_AI_SCORES):
        return calculate_score(symbol, df, news, fundamentals=fundamentals, spy_df=spy_df)


class TestScorer:
    def test_returns_required_keys(self, bull_df, sample_news):
        result = _patched_score("AAPL", bull_df, sample_news)
        required = ["symbol", "score", "signal", "regime", "timestamp", "indicators", "ai_layer"]
        assert all(k in result for k in required)

    def test_score_in_valid_range(self, bull_df, sample_news):
        result = _patched_score("NVDA", bull_df, sample_news)
        assert 0.0 <= result["score"] <= 1.0

    def test_signal_is_valid(self, bull_df, sample_news):
        result = _patched_score("MSFT", bull_df, sample_news)
        assert result["signal"] in ["STRONG_BUY", "BUY", "WATCH", "NEUTRAL"]

    def test_regime_is_valid(self, bull_df, sample_news):
        result = _patched_score("GOOGL", bull_df, sample_news)
        assert result["regime"] in ["BULL", "BEAR", "SIDEWAYS"]

    def test_symbol_preserved(self, flat_df, sample_news):
        result = _patched_score("TSLA", flat_df, sample_news)
        assert result["symbol"] == "TSLA"

    def test_timestamp_format(self, flat_df, sample_news):
        result = _patched_score("SPY", flat_df, sample_news)
        # Should be ISO format YYYY-MM-DDTHH:MM:SSZ
        assert "T" in result["timestamp"]
        assert result["timestamp"].endswith("Z")

    def test_bull_trend_higher_score_than_bear(self, bull_df, bear_df, sample_news):
        bull_result = _patched_score("AAPL", bull_df, sample_news)
        bear_result = _patched_score("AAPL", bear_df, sample_news)
        assert bull_result["score"] > bear_result["score"]

    def test_ai_layer_phase2_keys(self, flat_df, sample_news):
        """Phase 2 contract: ai_layer must have fear_greed, dalio_score, phase==PHASE_2_FG_RS."""
        result = _patched_score("AAPL", flat_df, sample_news)
        ai = result["ai_layer"]
        # Phase 2 scoring key (replaced dalio_macro from Phase 1)
        assert "fear_greed" in ai
        assert 0.0 <= ai["fear_greed"] <= 1.0
        # Dalio is metadata (display only)
        assert "dalio_score" in ai
        # Phase label
        assert ai["phase"] == "PHASE_2_FG_RS"
        # ai_disabled flag must be present
        assert "ai_disabled" in ai

    def test_ai_layer_score_values(self, flat_df, sample_news):
        """ai_layer scoring fields match the mock payload."""
        result = _patched_score("AAPL", flat_df, sample_news)
        ai = result["ai_layer"]
        assert ai["finbert"] == 0.6
        assert ai["fear_greed"] == 0.4
        assert ai["llm_pattern"] == 0.6
        assert ai["dalio_score"] == 0.5

    def test_all_indicators_present(self, bull_df, sample_news):
        result = _patched_score("AAPL", bull_df, sample_news)
        ind = result["indicators"]
        assert all(k in ind for k in ["ema", "supertrend", "rsi", "macd", "vwap", "volume", "atr"])

    def test_rs_bonus_when_outperforms_spy(self, sample_news):
        """RS bonus == 0.05 when stock outperforms SPY over 20 days."""
        # Stock goes up strongly; SPY stays flat
        stock_df = make_ohlcv(n=100, trend="bull")
        spy_df = make_ohlcv(n=100, trend="flat")
        result = _patched_score("AAPL", stock_df, sample_news, spy_df=spy_df)
        assert result["rs_bonus"] == 0.05

    def test_rs_bonus_zero_for_spy_itself(self, bull_df, sample_news):
        """SPY symbol never gets RS bonus (no self-comparison)."""
        spy_df = make_ohlcv(n=100, trend="bull")
        result = _patched_score("SPY", bull_df, sample_news, spy_df=spy_df)
        assert result["rs_bonus"] == 0.0

    def test_rs_bonus_zero_without_spy_df(self, bull_df, sample_news):
        """RS bonus is 0.0 when no spy_df is provided."""
        result = _patched_score("AAPL", bull_df, sample_news, spy_df=None)
        assert result["rs_bonus"] == 0.0

    def test_ai_disabled_flag_present(self, flat_df, sample_news):
        """When AI is mocked, ai_disabled must be False in our mock."""
        result = _patched_score("AAPL", flat_df, sample_news)
        assert result["ai_layer"]["ai_disabled"] is False
