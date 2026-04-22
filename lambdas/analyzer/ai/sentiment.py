"""
AlphaForge — News Sentiment Analyzer
Inspired by: BuffettLetters NLP project (github.com/biovino1/BuffettLetters)
Concept: Analyze financial text → normalize to score [0.0, 1.0] → feed into signal scoring.

Uses ai_router.py (TaskTier.MEDIUM) instead of FinBERT to keep cost < $5/month.
Phase 4: swap to actual FinBERT via AWS Bedrock or HuggingFace Inference API.
"""
import json
import logging
from typing import Any

from ai.ai_router import route, TaskTier

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """You are a financial sentiment analyst. Given news headlines about a stock,
output ONLY a JSON object in this exact format (no extra text):
{"score": <float 0.0-1.0>, "label": "<BULLISH|BEARISH|NEUTRAL>", "reasoning": "<one sentence>"}

Scoring guide:
- 0.8–1.0 = strongly bullish (earnings beat, breakout, upgrade, buyback)
- 0.6–0.79 = mildly bullish
- 0.4–0.59 = neutral (mixed signals, no clear direction)
- 0.2–0.39 = mildly bearish
- 0.0–0.19 = strongly bearish (earnings miss, downgrade, regulatory action, layoffs)"""


def analyze_news_sentiment(symbol: str, news: list[dict[str, str]]) -> dict[str, Any]:
    """
    Analyze news headlines for a stock and return a sentiment score.

    Args:
        symbol: Ticker symbol (e.g. "AAPL")
        news: List of dicts with keys: title, publisher, link (from fetcher.fetch_news)

    Returns:
        dict with keys: score (float 0.0–1.0), label (str), reasoning (str), source (str)
    """
    if not news:
        logger.info({"action": "sentiment_skip", "symbol": symbol, "reason": "no_news"})
        return _neutral_result("no_news")

    headlines = "\n".join(
        f"- {item['title']} ({item['publisher']})"
        for item in news
        if item.get("title")
    )

    if not headlines.strip():
        return _neutral_result("empty_headlines")

    prompt = f"""Stock: {symbol}
News headlines (most recent first):
{headlines}

Analyze the overall sentiment of these headlines for {symbol} stock."""

    try:
        raw = route(TaskTier.MEDIUM, prompt, system=_SYSTEM_PROMPT)
        result = _parse_response(raw)
        logger.info({
            "action": "sentiment_scored",
            "symbol": symbol,
            "score": result["score"],
            "label": result["label"],
        })
        return result
    except Exception as e:
        logger.warning({"action": "sentiment_failed", "symbol": symbol, "error": str(e)})
        return _neutral_result("ai_error")


def _parse_response(raw: str) -> dict[str, Any]:
    """Parse JSON from AI response, fallback to neutral on parse error."""
    try:
        # Strip markdown code fences if present
        clean = raw.strip()
        if clean.startswith("```"):
            clean = clean.split("```")[1]
            if clean.startswith("json"):
                clean = clean[4:]
        parsed = json.loads(clean.strip())
        score = float(parsed.get("score", 0.5))
        score = max(0.0, min(1.0, score))  # clamp to [0.0, 1.0]
        return {
            "score": round(score, 3),
            "label": parsed.get("label", "NEUTRAL"),
            "reasoning": parsed.get("reasoning", ""),
            "source": "ai_router",
        }
    except (json.JSONDecodeError, ValueError, KeyError):
        return _neutral_result("parse_error")


def _neutral_result(reason: str) -> dict[str, Any]:
    """Return a neutral score (0.5 = no contribution to signal score)."""
    return {
        "score": 0.5,
        "label": "NEUTRAL",
        "reasoning": f"fallback: {reason}",
        "source": "fallback",
    }
