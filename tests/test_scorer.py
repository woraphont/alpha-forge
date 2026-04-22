"""
AlphaForge — Tests for the scoring engine.
Run: pytest tests/test_scorer.py -v
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../lambdas/analyzer"))

import pytest
from conftest import make_ohlcv
from scorer import calculate_score


class TestScorer:
    def test_returns_required_keys(self, bull_df, sample_news):
        result = calculate_score("AAPL", bull_df, sample_news)
        required = ["symbol", "score", "signal", "regime", "timestamp", "indicators", "ai_layer"]
        assert all(k in result for k in required)

    def test_score_in_valid_range(self, bull_df, sample_news):
        result = calculate_score("NVDA", bull_df, sample_news)
        assert 0.0 <= result["score"] <= 1.0

    def test_signal_is_valid(self, bull_df, sample_news):
        result = calculate_score("MSFT", bull_df, sample_news)
        assert result["signal"] in ["STRONG_BUY", "BUY", "WATCH", "NEUTRAL"]

    def test_regime_is_valid(self, bull_df, sample_news):
        result = calculate_score("GOOGL", bull_df, sample_news)
        assert result["regime"] in ["BULL", "BEAR", "SIDEWAYS"]

    def test_symbol_preserved(self, flat_df, sample_news):
        result = calculate_score("TSLA", flat_df, sample_news)
        assert result["symbol"] == "TSLA"

    def test_timestamp_format(self, flat_df, sample_news):
        result = calculate_score("SPY", flat_df, sample_news)
        # Should be ISO format YYYY-MM-DDTHH:MM:SSZ
        assert "T" in result["timestamp"]
        assert result["timestamp"].endswith("Z")

    def test_bull_trend_higher_score_than_bear(self, bull_df, bear_df, sample_news):
        bull_result = calculate_score("AAPL", bull_df, sample_news)
        bear_result = calculate_score("AAPL", bear_df, sample_news)
        assert bull_result["score"] > bear_result["score"]

    def test_ai_layer_in_phase1_sentiment(self, flat_df, sample_news):
        from unittest.mock import patch
        mock_response = '{"score": 0.5, "label": "NEUTRAL", "reasoning": "no clear signal"}'
        with patch("ai.sentiment.route", return_value=mock_response):
            result = calculate_score("AAPL", flat_df, sample_news)
        ai = result["ai_layer"]
        assert 0.0 <= ai["finbert"] <= 1.0
        assert ai["dalio_macro"] == 0.5
        assert ai["llm_pattern"] == 0.5
        assert ai["phase"] == "PHASE_1_BUFFETT_DALIO"

    def test_all_indicators_present(self, bull_df, sample_news):
        result = calculate_score("AAPL", bull_df, sample_news)
        ind = result["indicators"]
        assert all(k in ind for k in ["ema", "supertrend", "rsi", "macd", "vwap", "volume", "atr"])
