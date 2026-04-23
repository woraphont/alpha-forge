"""
AlphaForge — Tests for technical indicators.
Run: pytest tests/test_technical.py -v
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../lambdas/analyzer"))

import pytest
from conftest import make_ohlcv
from technical.trend import calculate_ema, calculate_supertrend
from technical.momentum import calculate_rsi, calculate_macd
from technical.volume import calculate_vwap, calculate_volume_ratio
from technical.volatility import calculate_atr


class TestEMA:
    def test_returns_required_keys(self, bull_df):
        result = calculate_ema(bull_df)
        assert all(k in result for k in ["score", "signal", "ema20", "ema50", "ema200", "current"])

    def test_bull_trend_positive_score(self, bull_df):
        result = calculate_ema(bull_df)
        assert result["score"] > 0

    def test_bear_trend_negative_score(self, bear_df):
        result = calculate_ema(bear_df)
        assert result["score"] <= 0

    def test_score_within_range(self, bull_df):
        result = calculate_ema(bull_df)
        assert -0.15 <= result["score"] <= 0.15

    def test_golden_stack_signal(self, bull_df):
        result = calculate_ema(bull_df)
        # Strong bull should produce golden stack or partial bull
        assert result["signal"] in ["GOLDEN_STACK", "PARTIAL_BULL", "MIXED"]


class TestSupertrend:
    def test_returns_required_keys(self, bull_df):
        result = calculate_supertrend(bull_df)
        assert all(k in result for k in ["score", "direction", "support", "resistance", "atr"])

    def test_direction_is_valid(self, bull_df):
        result = calculate_supertrend(bull_df)
        assert result["direction"] in ["UP", "DOWN"]

    def test_score_binary(self, bull_df):
        result = calculate_supertrend(bull_df)
        assert result["score"] in [0.10, -0.10]

    def test_bull_series_is_up(self, bull_df):
        """A clearly uptrending series should produce direction == UP."""
        result = calculate_supertrend(bull_df)
        assert result["direction"] == "UP"
        assert result["score"] == 0.10

    def test_bear_series_is_down(self, bear_df):
        """A clearly downtrending series should produce direction == DOWN."""
        result = calculate_supertrend(bear_df)
        assert result["direction"] == "DOWN"
        assert result["score"] == -0.10

    def test_bull_bear_produce_different_scores(self, bull_df, bear_df):
        """Bull and bear series must give different Supertrend scores (stateful = not all same)."""
        bull_result = calculate_supertrend(bull_df)
        bear_result = calculate_supertrend(bear_df)
        assert bull_result["score"] != bear_result["score"]
        assert bull_result["direction"] != bear_result["direction"]

    def test_atr_is_positive(self, flat_df):
        result = calculate_supertrend(flat_df)
        assert result["atr"] > 0


class TestRSI:
    def test_returns_required_keys(self, flat_df):
        result = calculate_rsi(flat_df)
        assert all(k in result for k in ["score", "signal", "rsi"])

    def test_rsi_range(self, flat_df):
        result = calculate_rsi(flat_df)
        assert 0 <= result["rsi"] <= 100

    def test_score_range(self, flat_df):
        result = calculate_rsi(flat_df)
        assert -0.10 <= result["score"] <= 0.10

    def test_valid_signal(self, flat_df):
        result = calculate_rsi(flat_df)
        assert result["signal"] in ["OVERSOLD", "RECOVERY_ZONE", "NEUTRAL", "OVERBOUGHT"]


class TestMACD:
    def test_returns_required_keys(self, bull_df):
        result = calculate_macd(bull_df)
        assert all(k in result for k in ["score", "signal", "histogram", "macd_line", "signal_line"])

    def test_score_range(self, bull_df):
        result = calculate_macd(bull_df)
        assert -0.10 <= result["score"] <= 0.10

    def test_valid_signal(self, bull_df):
        result = calculate_macd(bull_df)
        valid = ["BULLISH_CROSS", "BEARISH_CROSS", "HISTOGRAM_RISING", "HISTOGRAM_FALLING", "NEUTRAL"]
        assert result["signal"] in valid


class TestVWAP:
    def test_returns_required_keys(self, flat_df):
        result = calculate_vwap(flat_df)
        assert all(k in result for k in ["score", "vwap", "current", "above_vwap", "pct_vs_vwap"])

    def test_score_range(self, flat_df):
        result = calculate_vwap(flat_df)
        assert result["score"] in [0.07, -0.03]

    def test_vwap_positive(self, flat_df):
        result = calculate_vwap(flat_df)
        assert result["vwap"] > 0


class TestATR:
    def test_returns_required_keys(self, flat_df):
        result = calculate_atr(flat_df)
        assert all(k in result for k in ["score", "atr", "atr_avg", "atr_pct", "regime"])

    def test_atr_positive(self, flat_df):
        result = calculate_atr(flat_df)
        assert result["atr"] > 0

    def test_score_non_negative(self, flat_df):
        result = calculate_atr(flat_df)
        assert result["score"] >= 0

    def test_regime_valid(self, flat_df):
        result = calculate_atr(flat_df)
        assert result["regime"] in ["LOW_VOL", "HIGH_VOL"]
