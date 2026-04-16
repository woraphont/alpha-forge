"""
AlphaForge — Trend Indicators
EMA alignment + Supertrend
"""
import logging

import pandas as pd

logger = logging.getLogger(__name__)


def calculate_ema(df: pd.DataFrame) -> dict:
    """
    EMA 20/50/200 alignment scoring.

    Score:
        +0.15  → Golden Stack (20 > 50 > 200) — strong bull trend
        +0.08  → Partial bull (20 > 50 only)
        -0.10  → Death Stack (20 < 50 < 200) — strong bear trend
         0.00  → Mixed / neutral
    """
    close = df["Close"]
    ema20 = float(close.ewm(span=20, adjust=False).mean().iloc[-1])
    ema50 = float(close.ewm(span=50, adjust=False).mean().iloc[-1])
    ema200 = float(close.ewm(span=200, adjust=False).mean().iloc[-1])
    current = float(close.iloc[-1])

    if ema20 > ema50 > ema200:
        score, signal = 0.15, "GOLDEN_STACK"
    elif ema20 > ema50:
        score, signal = 0.08, "PARTIAL_BULL"
    elif ema20 < ema50 < ema200:
        score, signal = -0.10, "DEATH_STACK"
    else:
        score, signal = 0.00, "MIXED"

    return {
        "score": score,
        "signal": signal,
        "ema20": round(ema20, 2),
        "ema50": round(ema50, 2),
        "ema200": round(ema200, 2),
        "current": round(current, 2),
    }


def calculate_supertrend(df: pd.DataFrame, period: int = 10, multiplier: float = 3.0) -> dict:
    """
    Supertrend indicator — ATR-based dynamic trend direction.

    Score:
        +0.10 → Supertrend direction = UP (price above support band)
        -0.10 → Supertrend direction = DOWN (price below resistance band)
    """
    high = df["High"]
    low = df["Low"]
    close = df["Close"]

    # True Range
    tr = pd.concat([
        high - low,
        (high - close.shift(1)).abs(),
        (low - close.shift(1)).abs(),
    ], axis=1).max(axis=1)

    atr = tr.ewm(span=period, adjust=False).mean()
    hl2 = (high + low) / 2
    upper_band = hl2 + multiplier * atr
    lower_band = hl2 - multiplier * atr

    current_close = float(close.iloc[-1])
    current_lower = float(lower_band.iloc[-1])
    current_upper = float(upper_band.iloc[-1])
    current_atr = float(atr.iloc[-1])

    direction = "UP" if current_close > current_lower else "DOWN"
    score = 0.10 if direction == "UP" else -0.10

    return {
        "score": score,
        "direction": direction,
        "support": round(current_lower, 2),
        "resistance": round(current_upper, 2),
        "atr": round(current_atr, 2),
    }
