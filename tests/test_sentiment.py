"""
AlphaForge — Tests for ai/sentiment.py
Run: pytest tests/test_sentiment.py -v
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../lambdas/analyzer"))

from unittest.mock import patch
import pytest


class TestAnalyzeNewsSentiment:
    def test_returns_neutral_when_no_news(self):
        from ai.sentiment import analyze_news_sentiment
        result = analyze_news_sentiment("AAPL", [])
        assert result["score"] == 0.5
        assert result["label"] == "NEUTRAL"
        assert result["source"] == "fallback"

    def test_returns_neutral_on_empty_titles(self):
        from ai.sentiment import analyze_news_sentiment
        news = [{"title": "", "publisher": "Reuters", "link": ""}]
        result = analyze_news_sentiment("AAPL", news)
        assert result["score"] == 0.5

    def test_score_in_valid_range(self):
        from ai.sentiment import analyze_news_sentiment
        mock_response = '{"score": 0.82, "label": "BULLISH", "reasoning": "Strong earnings beat"}'
        with patch("ai.sentiment.route", return_value=mock_response):
            result = analyze_news_sentiment("NVDA", [{"title": "NVDA beats estimates", "publisher": "Reuters", "link": ""}])
        assert 0.0 <= result["score"] <= 1.0
        assert result["label"] == "BULLISH"
        assert result["source"] == "ai_router"

    def test_score_clamped_above_1(self):
        from ai.sentiment import _parse_response
        result = _parse_response('{"score": 1.5, "label": "BULLISH", "reasoning": "test"}')
        assert result["score"] == 1.0

    def test_score_clamped_below_0(self):
        from ai.sentiment import _parse_response
        result = _parse_response('{"score": -0.3, "label": "BEARISH", "reasoning": "test"}')
        assert result["score"] == 0.0

    def test_fallback_on_invalid_json(self):
        from ai.sentiment import _parse_response
        result = _parse_response("this is not json")
        assert result["score"] == 0.5
        assert result["source"] == "fallback"

    def test_strips_markdown_fences(self):
        from ai.sentiment import _parse_response
        raw = '```json\n{"score": 0.7, "label": "BULLISH", "reasoning": "positive"}\n```'
        result = _parse_response(raw)
        assert result["score"] == 0.7

    def test_fallback_on_ai_error(self):
        from ai.sentiment import analyze_news_sentiment
        with patch("ai.sentiment.route", side_effect=RuntimeError("all models failed")):
            result = analyze_news_sentiment("TSLA", [{"title": "TSLA news", "publisher": "Bloomberg", "link": ""}])
        assert result["score"] == 0.5
        assert "ai_error" in result["reasoning"]
