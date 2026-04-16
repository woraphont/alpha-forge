"""
AlphaForge — Scoring Engine v2.0
Combines technical indicators + AI layer into a single score [0.0, 1.0].

Phase 1: AI layer (FinBERT / LLM Pattern / Fear&Greed) = placeholder 0.5 (neutral)
Phase 2: Full AI layer implemented
"""
import logging
from datetime import datetime, timezone
from typing import Any

import pandas as pd

from technical.trend import calculate_ema, calculate_supertrend
from technical.momentum import calculate_rsi, calculate_macd
from technical.volume import calculate_vwap, calculate_volume_ratio
from technical.volatility import calculate_atr

logger = logging.getLogger(__name__)


def _get_ai_scores(symbol: str, df: pd.DataFrame, news: list[dict]) -> dict[str, float]:
    """
    AI indicator scores.
    Phase 1: returns neutral placeholders (0.5 = no contribution to score).
    Phase 2: implements FinBERT + Fear&Greed + LLM Pattern Recognition.
    """
    # TODO Phase 2: implement FinBERT sentiment from news headlines
    # from ai.finbert import calculate_finbert_sentiment
    # finbert = calculate_finbert_sentiment(news)

    # TODO Phase 2: implement Fear & Greed Index fetch
    # from ai.fear_greed import get_fear_greed_score
    # fear_greed = get_fear_greed_score()

    # TODO Phase 2: implement LLM pattern recognition
    # from ai.pattern import classify_chart_pattern
    # llm_pattern = classify_chart_pattern(symbol, df)

    return {
        "finbert": 0.5,       # neutral until Phase 2
        "fear_greed": 0.5,    # neutral until Phase 2
        "llm_pattern": 0.5,   # neutral until Phase 2
        "phase": "PHASE_1_PLACEHOLDER",
    }


def _get_regime_multiplier(df: pd.DataFrame) -> tuple[float, str]:
    """
    Simple market regime detection using EMA slopes.
    Phase 4: upgrade to ML-based regime classifier.

    Returns: (multiplier, regime_name)
    """
    close = df["Close"]
    ema50 = close.ewm(span=50, adjust=False).mean()
    slope = float(ema50.iloc[-1]) - float(ema50.iloc[-10])

    if slope > 0:
        return 1.2, "BULL"
    elif slope < -0.5:
        return 0.8, "BEAR"
    else:
        return 1.0, "SIDEWAYS"


def calculate_score(symbol: str, df: pd.DataFrame, news: list[dict]) -> dict[str, Any]:
    """
    Calculate composite signal score for a US stock.

    Formula:
        score = EMA(0.15) + Supertrend(0.10) + RSI(0.10) + MACD(0.10)
              + VWAP(0.07) + ATR(0.03)
              + FinBERT(0.20) + FearGreed(0.05) + LLM_Pattern(0.15)
              × RegimeMultiplier

    Returns:
        dict with score [0.0–1.0], signal, timestamp, and all indicator details
    """
    # Technical indicators
    ema_res      = calculate_ema(df)
    st_res       = calculate_supertrend(df)
    rsi_res      = calculate_rsi(df)
    macd_res     = calculate_macd(df)
    vwap_res     = calculate_vwap(df)
    vol_res      = calculate_volume_ratio(df)
    atr_res      = calculate_atr(df)

    # AI layer (Phase 1 = placeholders)
    ai_scores    = _get_ai_scores(symbol, df, news)
    regime_mult, regime = _get_regime_multiplier(df)

    # Raw score (before normalization)
    # AI components centered at 0.5 → contribution = (score - 0.5) × weight
    raw_score = (
        ema_res["score"]                              # weight 0.15
        + st_res["score"]                            # weight 0.10
        + rsi_res["score"]                           # weight 0.10
        + macd_res["score"]                          # weight 0.10
        + vwap_res["score"]                          # weight 0.07
        + atr_res["score"]                           # weight 0.03
        + (ai_scores["finbert"]    - 0.5) * 0.20    # weight 0.20
        + (ai_scores["fear_greed"] - 0.5) * 0.05    # weight 0.05
        + (ai_scores["llm_pattern"]- 0.5) * 0.15    # weight 0.15
    )

    # Apply regime multiplier then normalize to [0.0, 1.0]
    # Base at 0.5 so neutral TA = 0.5 score
    score = max(0.0, min(1.0, raw_score * regime_mult + 0.5))

    # Signal classification
    if score >= 0.75:
        signal = "STRONG_BUY"
    elif score >= 0.55:
        signal = "BUY"
    elif score >= 0.35:
        signal = "WATCH"
    else:
        signal = "NEUTRAL"

    result = {
        "symbol": symbol,
        "score": round(score, 3),
        "signal": signal,
        "regime": regime,
        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "indicators": {
            "ema":        ema_res,
            "supertrend": st_res,
            "rsi":        rsi_res,
            "macd":       macd_res,
            "vwap":       vwap_res,
            "volume":     vol_res,
            "atr":        atr_res,
        },
        "ai_layer": ai_scores,
    }

    logger.info({
        "action": "scored",
        "symbol": symbol,
        "score": score,
        "signal": signal,
        "regime": regime,
        "regime_mult": regime_mult,
    })

    return result
