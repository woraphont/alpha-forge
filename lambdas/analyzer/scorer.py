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


def _get_ai_scores(symbol: str, df: pd.DataFrame, news: list[dict], fundamentals: dict) -> dict[str, float]:
    """
    AI indicator scores.
    - finbert (0.20):     news sentiment via ai_router (BuffettLetters-inspired)
    - llm_pattern (0.15): Buffett framework via ai_router + fundamentals
                          (buffett-perspective + ai-investor inspired)
    - dalio_macro (0.05): Dalio macro regime (debt cycle / inflation / USD)
                          replaces fear_greed placeholder
                          Phase 2: add FRED API data (CPI, yield curve, DXY)
    Phase 4: migrate all AI calls to AWS Bedrock.
    """
    from ai.sentiment import analyze_news_sentiment
    from ai.llm_pattern import analyze_pattern
    from ai.dalio_macro import analyze_macro

    sentiment = analyze_news_sentiment(symbol, news)
    pattern = analyze_pattern(symbol, df, fundamentals)
    dalio = analyze_macro(symbol, df, fundamentals)

    return {
        "finbert": sentiment["score"],          # news sentiment (0.0–1.0)
        "finbert_label": sentiment["label"],    # BULLISH / BEARISH / NEUTRAL
        "finbert_source": sentiment["source"],
        "llm_pattern": pattern["score"],        # Buffett framework score (0.0–1.0)
        "llm_signal": pattern["signal"],        # BULLISH / NEUTRAL / BEARISH
        "llm_moat": pattern["moat"],            # WIDE / NARROW / NONE
        "llm_reasoning": pattern["reasoning"],
        "dalio_macro": dalio["score"],          # Dalio macro regime score (0.0–1.0)
        "dalio_regime": dalio["regime"],        # RISK_ON / RISK_OFF / DELEVERAGING
        "dalio_cycle": dalio["cycle"],          # EXPANSION / CONTRACTION / DELEVERAGING
        "dalio_bias": dalio["macro_bias"],
        "phase": "PHASE_1_BUFFETT_DALIO",
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


def calculate_score(symbol: str, df: pd.DataFrame, news: list[dict], fundamentals: dict | None = None) -> dict[str, Any]:
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

    # AI layer
    ai_scores    = _get_ai_scores(symbol, df, news, fundamentals or {})
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
        + (ai_scores["finbert"]     - 0.5) * 0.20    # weight 0.20
        + (ai_scores["dalio_macro"] - 0.5) * 0.05   # weight 0.05 (was fear_greed)
        + (ai_scores["llm_pattern"] - 0.5) * 0.15   # weight 0.15
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
