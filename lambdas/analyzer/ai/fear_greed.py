"""
AlphaForge — Fear & Greed Index (Phase 2)
CNN Fear & Greed Index — free, no API key needed.

Contrarian signal (Buffett: "be fearful when others are greedy"):
  Extreme Fear  (0–25)  → score 0.85 (buy opportunity)
  Fear          (26–44) → score 0.65 (mild buy)
  Neutral       (45–55) → score 0.50
  Greed         (56–74) → score 0.35 (mild caution)
  Extreme Greed (75–100)→ score 0.15 (sell signal)

Source: https://production.dataviz.cnn.io/index/fearandgreed/graphdata
Phase 4: consider alternative sources if CNN changes API structure.
"""
import logging
from typing import Any

import requests

logger = logging.getLogger(__name__)

_CNN_FG_URL = "https://production.dataviz.cnn.io/index/fearandgreed/graphdata"
_TIMEOUT = 5  # seconds — fail fast, don't hold up the Lambda


def fetch_fear_greed() -> dict[str, Any]:
    """
    Fetch CNN Fear & Greed Index and return a contrarian sentiment score.

    Returns:
        dict with keys:
            score  (float 0.0–1.0) — contrarian score for use in signal formula
            value  (int 0–100)     — raw CNN index value
            rating (str)           — human label: "Extreme Fear", "Greed", etc.
            source (str)           — data source identifier
    """
    try:
        resp = requests.get(
            _CNN_FG_URL,
            timeout=_TIMEOUT,
            headers={"User-Agent": "Mozilla/5.0 (AlphaForge/2.0)"},
        )
        resp.raise_for_status()
        data = resp.json()

        fg_value = int(data["fear_and_greed"]["score"])
        fg_rating = str(data["fear_and_greed"]["rating"])

        contrarian_score = _value_to_contrarian_score(fg_value)

        result: dict[str, Any] = {
            "score": contrarian_score,
            "value": fg_value,
            "rating": fg_rating,
            "source": "cnn_fear_greed",
        }
        logger.info({
            "action": "fear_greed_fetched",
            "value": fg_value,
            "rating": fg_rating,
            "contrarian_score": contrarian_score,
        })
        return result

    except Exception as e:
        logger.warning({"action": "fear_greed_failed", "error": str(e)})
        return _neutral_result("api_error")


def _value_to_contrarian_score(value: int) -> float:
    """Convert raw 0–100 Fear & Greed value to contrarian score [0.0–1.0]."""
    if value <= 25:
        return 0.85   # Extreme Fear → buy opportunity
    if value <= 44:
        return 0.65   # Fear → mild buy
    if value <= 55:
        return 0.50   # Neutral
    if value <= 74:
        return 0.35   # Greed → mild caution
    return 0.15       # Extreme Greed → sell signal


def _neutral_result(reason: str) -> dict[str, Any]:
    return {
        "score": 0.50,
        "value": None,
        "rating": "UNKNOWN",
        "source": f"fallback:{reason}",
    }
