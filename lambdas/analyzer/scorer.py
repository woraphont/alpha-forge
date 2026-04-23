"""
AlphaForge — Scoring Engine v2.0 (Phase 2)
Combines technical indicators + AI layer into a single score [0.0, 1.0].

Formula:
    score = EMA(0.15) + Supertrend(0.10) + RSI(0.10) + MACD(0.10)
          + VWAP(0.07) + ATR(0.03)
          + FinBERT(0.20) + FearGreed(0.05) + LLM_Pattern(0.15)
          × RegimeMultiplier(Bull=1.2, Bear=0.8, Sideways=1.0)
          + RS_bonus(+0.05 if stock outperforms SPY over 20 days)

Phase 2 changes vs Phase 1:
  - fear_greed replaces dalio_macro in scoring formula (dalio stays as metadata)
  - RS_bonus added (Relative Strength vs SPY)
  - spy_df passed in from handler (fetched once per Lambda invocation)
"""
import logging
import os
from datetime import datetime, timezone
from typing import Any

import pandas as pd

from technical.trend import calculate_ema, calculate_supertrend
from technical.momentum import calculate_rsi, calculate_macd
from technical.volume import calculate_vwap, calculate_volume_ratio
from technical.volatility import calculate_atr

logger = logging.getLogger(__name__)

_AI_ENABLED = os.environ.get("AI_ENABLED", "true").lower() == "true"


def _get_ai_scores(
    symbol: str,
    df: pd.DataFrame,
    news: list[dict],
    fundamentals: dict,
) -> dict[str, Any]:
    """
    AI indicator scores (Phase 2):
      - finbert    (0.20): news sentiment via ai_router (LLM-based, GPT-mini)
      - fear_greed (0.05): CNN Fear & Greed contrarian index (replaces dalio_macro in formula)
      - llm_pattern(0.15): Buffett framework via Claude Haiku + fundamentals
      - dalio_macro(meta): Dalio regime — NOT in score, used for Telegram display + FRED data
    Phase 4: migrate AI calls to AWS Bedrock.
    """
    _FALLBACK: dict[str, Any] = {
        "finbert": 0.5, "fear_greed": 0.5, "llm_pattern": 0.5,
        "finbert_label": "NEUTRAL", "finbert_source": "fallback",
        "fg_value": None, "fg_rating": "UNKNOWN",
        "llm_signal": "NEUTRAL", "llm_moat": "UNKNOWN", "llm_valuation": "UNKNOWN",
        "llm_reasoning": "", "llm_key_concern": None,
        "dalio_score": 0.5, "dalio_regime": "RISK_OFF", "dalio_cycle": "CONTRACTION",
        "dalio_season": "D_DEFLATION", "dalio_big_cycle": None,
        "dalio_bias": "fallback", "dalio_key_risk": None,
        "phase": "PHASE_2_FG_RS",
        "ai_disabled": False,
    }

    if not _AI_ENABLED:
        logger.warning({
            "action": "ai_scores_disabled",
            "symbol": symbol,
            "reason": "AI_ENABLED=false — returning neutral fallback scores",
        })
        return {**_FALLBACK, "ai_disabled": True, "reason": "AI_ENABLED=false"}

    try:
        from ai.sentiment import analyze_news_sentiment
    except ImportError as e:
        logger.warning({
            "action": "ai_import_failed",
            "symbol": symbol,
            "missing_module": str(e),
            "reason": "sentiment module unavailable — returning neutral fallback",
        })
        return {**_FALLBACK, "ai_disabled": True, "reason": f"ImportError: {e}"}

    try:
        from ai.llm_pattern import analyze_pattern
    except ImportError as e:
        logger.warning({
            "action": "ai_import_failed",
            "symbol": symbol,
            "missing_module": str(e),
            "reason": "llm_pattern module unavailable — returning neutral fallback",
        })
        return {**_FALLBACK, "ai_disabled": True, "reason": f"ImportError: {e}"}

    try:
        from ai.dalio_macro import analyze_macro
    except ImportError as e:
        logger.warning({
            "action": "ai_import_failed",
            "symbol": symbol,
            "missing_module": str(e),
            "reason": "dalio_macro module unavailable — returning neutral fallback",
        })
        return {**_FALLBACK, "ai_disabled": True, "reason": f"ImportError: {e}"}

    try:
        from ai.fear_greed import fetch_fear_greed
    except ImportError as e:
        logger.warning({
            "action": "ai_import_failed",
            "symbol": symbol,
            "missing_module": str(e),
            "reason": "fear_greed module unavailable — returning neutral fallback",
        })
        return {**_FALLBACK, "ai_disabled": True, "reason": f"ImportError: {e}"}

    sentiment = analyze_news_sentiment(symbol, news)
    pattern = analyze_pattern(symbol, df, fundamentals)
    dalio = analyze_macro(symbol, df, fundamentals)
    fg = fetch_fear_greed()

    return {
        # Scoring components
        "finbert":         sentiment["score"],
        "fear_greed":      fg["score"],
        "llm_pattern":     pattern["score"],
        # Metadata (display only — not in score formula)
        "finbert_label":   sentiment["label"],
        "finbert_source":  sentiment["source"],
        "fg_value":        fg["value"],
        "fg_rating":       fg["rating"],
        "llm_signal":      pattern["signal"],
        "llm_moat":        pattern["moat"],
        "llm_valuation":   pattern["valuation"],
        "llm_reasoning":   pattern["reasoning"],
        "llm_key_concern": pattern.get("key_concern"),
        "dalio_score":     dalio["score"],
        "dalio_regime":    dalio["regime"],
        "dalio_cycle":     dalio["cycle"],
        "dalio_season":    dalio.get("season"),
        "dalio_big_cycle": dalio.get("big_cycle"),
        "dalio_bias":      dalio["macro_bias"],
        "dalio_key_risk":  dalio.get("key_risk"),
        "phase": "PHASE_2_FG_RS",
        "ai_disabled": False,
    }


def _get_regime_multiplier(df: pd.DataFrame) -> tuple[float, str]:
    """
    Simple market regime detection using EMA50 slope.
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


def _calculate_rs_bonus(symbol: str, df: pd.DataFrame, spy_df: pd.DataFrame | None) -> float:
    """
    Relative Strength bonus: +0.05 if stock's 20-day return > SPY's 20-day return.
    RS > 1.0 = stock outperforms market = momentum confirmation.

    Returns: 0.05 (bonus) or 0.0 (no bonus)
    """
    if symbol == "SPY" or spy_df is None or spy_df.empty:
        return 0.0

    try:
        if len(df) < 21 or len(spy_df) < 21:
            return 0.0

        stock_return = float(df["Close"].iloc[-1]) / float(df["Close"].iloc[-20]) - 1
        spy_return = float(spy_df["Close"].iloc[-1]) / float(spy_df["Close"].iloc[-20]) - 1

        # RS ratio: >1.0 = stock outperforms SPY
        rs = (1 + stock_return) / (1 + spy_return) if (1 + spy_return) != 0 else 1.0
        bonus = 0.05 if rs > 1.0 else 0.0
        logger.info({"action": "rs_bonus", "symbol": symbol,
                     "stock_ret": round(stock_return, 4),
                     "spy_ret": round(spy_return, 4),
                     "rs": round(rs, 3), "bonus": bonus})
        return bonus
    except Exception as e:
        logger.warning({"action": "rs_bonus_failed", "symbol": symbol, "error": str(e)})
        return 0.0


def calculate_score(
    symbol: str,
    df: pd.DataFrame,
    news: list[dict],
    fundamentals: dict | None = None,
    spy_df: pd.DataFrame | None = None,
) -> dict[str, Any]:
    """
    Calculate composite signal score for a US stock.

    Args:
        symbol:       Ticker symbol (e.g. "AAPL")
        df:           OHLCV DataFrame (≥60 days recommended)
        news:         List of news dicts from fetcher.fetch_news()
        fundamentals: Output from fetcher.fetch_fundamentals()
        spy_df:       SPY OHLCV DataFrame for RS bonus (optional, fetched once in handler)

    Returns:
        dict with score [0.0–1.0], signal, timestamp, and all indicator details
    """
    # Technical indicators
    ema_res  = calculate_ema(df)
    st_res   = calculate_supertrend(df)
    rsi_res  = calculate_rsi(df)
    macd_res = calculate_macd(df)
    vwap_res = calculate_vwap(df)
    vol_res  = calculate_volume_ratio(df)
    atr_res  = calculate_atr(df)

    # AI layer + Fear & Greed
    ai_scores    = _get_ai_scores(symbol, df, news, fundamentals or {})
    regime_mult, regime = _get_regime_multiplier(df)
    rs_bonus     = _calculate_rs_bonus(symbol, df, spy_df)

    # Raw score (technical components already return delta from neutral)
    # AI components centered at 0.5 → contribution = (score - 0.5) × weight
    raw_score = (
        ema_res["score"]                                # weight 0.15
        + st_res["score"]                              # weight 0.10
        + rsi_res["score"]                             # weight 0.10
        + macd_res["score"]                            # weight 0.10
        + vwap_res["score"]                            # weight 0.07
        + atr_res["score"]                             # weight 0.03
        + (ai_scores["finbert"]     - 0.5) * 0.20     # weight 0.20
        + (ai_scores["fear_greed"]  - 0.5) * 0.05     # weight 0.05 (Phase 2: was dalio_macro)
        + (ai_scores["llm_pattern"] - 0.5) * 0.15     # weight 0.15
    )

    # Apply regime multiplier → normalize to [0.0, 1.0] → add RS bonus
    score = max(0.0, min(1.0, raw_score * regime_mult + 0.5 + rs_bonus))

    # Signal classification
    if score >= 0.75:
        signal = "STRONG_BUY"
    elif score >= 0.55:
        signal = "BUY"
    elif score >= 0.35:
        signal = "WATCH"
    else:
        signal = "NEUTRAL"

    result: dict[str, Any] = {
        "symbol":    symbol,
        "score":     round(score, 3),
        "signal":    signal,
        "regime":    regime,
        "rs_bonus":  rs_bonus,
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
        "action":       "scored",
        "symbol":       symbol,
        "score":        score,
        "signal":       signal,
        "regime":       regime,
        "regime_mult":  regime_mult,
        "rs_bonus":     rs_bonus,
        "finbert":      round(ai_scores["finbert"], 3),
        "fear_greed":   ai_scores["fg_value"],
        "llm_pattern":  round(ai_scores["llm_pattern"], 3),
        "dalio_regime": ai_scores["dalio_regime"],
    })

    return result
