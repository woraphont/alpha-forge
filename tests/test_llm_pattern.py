"""
AlphaForge — Tests for ai/llm_pattern.py (Buffett Framework)
Run: pytest tests/test_llm_pattern.py -v
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../lambdas/analyzer"))

from unittest.mock import patch
import pytest
from conftest import make_ohlcv


FULL_FUNDAMENTALS = {
    "symbol": "AAPL",
    "roe": 0.175,
    "debt_to_equity": 0.4,
    "operating_margin": 0.29,
    "current_ratio": 1.6,
    "net_income": 97_000_000_000,
    "depreciation": 11_000_000_000,
    "capex": 10_000_000_000,
    "owner_earnings": 103_000_000_000,
}

EMPTY_FUNDAMENTALS = {
    "symbol": "AAPL", "roe": None, "debt_to_equity": None,
    "operating_margin": None, "current_ratio": None,
    "net_income": None, "depreciation": None, "capex": None, "owner_earnings": None,
}


class TestScoreFundamentals:
    def test_full_passing_fundamentals(self):
        from ai.llm_pattern import _score_fundamentals
        result = _score_fundamentals(FULL_FUNDAMENTALS)
        assert result["pre_score"] == 1.0
        assert result["checks"]["roe_ok"] is True
        assert result["checks"]["low_debt"] is True
        assert result["checks"]["margin_ok"] is True
        assert result["checks"]["liquid_ok"] is True

    def test_empty_fundamentals_returns_neutral_prescore(self):
        from ai.llm_pattern import _score_fundamentals
        result = _score_fundamentals(EMPTY_FUNDAMENTALS)
        assert result["pre_score"] == 0.5

    def test_weak_fundamentals_low_score(self):
        from ai.llm_pattern import _score_fundamentals
        weak = {**FULL_FUNDAMENTALS, "roe": 0.05, "debt_to_equity": 2.0,
                "operating_margin": 0.05, "current_ratio": 0.8,
                "owner_earnings": -1_000_000_000}
        result = _score_fundamentals(weak)
        assert result["pre_score"] < 0.3


class TestAnalyzePattern:
    def test_returns_valid_score(self):
        from ai.llm_pattern import analyze_pattern
        df = make_ohlcv(50, trend="up")
        mock = '{"score": 0.80, "signal": "BULLISH", "moat": "WIDE", "reasoning": "Strong fundamentals."}'
        with patch("ai.llm_pattern.route", return_value=mock):
            result = analyze_pattern("AAPL", df, FULL_FUNDAMENTALS)
        assert 0.0 <= result["score"] <= 1.0
        assert result["signal"] == "BULLISH"
        assert result["moat"] == "WIDE"
        assert result["source"] == "buffett_framework_v2"

    def test_fallback_on_ai_error(self):
        from ai.llm_pattern import analyze_pattern
        df = make_ohlcv(50, trend="up")
        with patch("ai.llm_pattern.route", side_effect=RuntimeError("all models failed")):
            result = analyze_pattern("TSLA", df, EMPTY_FUNDAMENTALS)
        assert result["score"] == 0.5
        assert result["source"] == "fallback"

    def test_strips_markdown_fences(self):
        from ai.llm_pattern import _parse_response
        raw = '```json\n{"score": 0.65, "signal": "BULLISH", "moat": "NARROW", "reasoning": "ok"}\n```'
        result = _parse_response(raw)
        assert result["score"] == 0.65

    def test_score_clamped(self):
        from ai.llm_pattern import _parse_response
        result = _parse_response('{"score": 1.99, "signal": "BULLISH", "moat": "WIDE", "reasoning": "ok"}')
        assert result["score"] == 1.0
