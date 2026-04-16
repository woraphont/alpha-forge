"""
AlphaForge — Volatility Indicators
ATR (Average True Range) — used as regime filter
"""
import logging

import pandas as pd

logger = logging.getLogger(__name__)


def calculate_atr(df: pd.DataFrame, period: int = 14) -> dict:
    """
    ATR regime filter.
    Low volatility = cleaner signals, higher score confidence.
    High volatility = noisy signals, filter out or reduce weight.

    Score:
        +0.03 → ATR < 20-day ATR avg (low vol = clean trend)
         0.00 → ATR >= 20-day ATR avg (high vol = caution)
    """
    high = df["High"]
    low = df["Low"]
    close = df["Close"]

    tr = pd.concat([
        high - low,
        (high - close.shift(1)).abs(),
        (low - close.shift(1)).abs(),
    ], axis=1).max(axis=1)

    atr = tr.rolling(period).mean()
    current_atr = float(atr.iloc[-1])
    avg_atr = float(atr.rolling(20).mean().iloc[-1])

    low_volatility = current_atr < avg_atr
    score = 0.03 if low_volatility else 0.00

    # ATR as % of price (normalized)
    current_price = float(close.iloc[-1])
    atr_pct = (current_atr / current_price * 100) if current_price > 0 else 0.0

    return {
        "score": score,
        "atr": round(current_atr, 2),
        "atr_avg": round(avg_atr, 2),
        "atr_pct": round(atr_pct, 2),
        "regime": "LOW_VOL" if low_volatility else "HIGH_VOL",
    }
