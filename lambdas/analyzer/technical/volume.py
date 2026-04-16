"""
AlphaForge — Volume Indicators
VWAP position + Volume ratio (20-day average)
"""
import logging

import pandas as pd

logger = logging.getLogger(__name__)


def calculate_vwap(df: pd.DataFrame) -> dict:
    """
    VWAP (Volume Weighted Average Price) over the lookback window.
    Institutional traders use VWAP as benchmark — price > VWAP = buying pressure.

    Score:
        +0.07 → Price > VWAP (institutional buying pressure)
        -0.03 → Price < VWAP (selling pressure)
    """
    typical_price = (df["High"] + df["Low"] + df["Close"]) / 3
    vwap = float((typical_price * df["Volume"]).sum() / df["Volume"].sum())
    current = float(df["Close"].iloc[-1])

    above_vwap = current > vwap
    score = 0.07 if above_vwap else -0.03

    return {
        "score": score,
        "vwap": round(vwap, 2),
        "current": round(current, 2),
        "above_vwap": above_vwap,
        "pct_vs_vwap": round((current - vwap) / vwap * 100, 2),
    }


def calculate_volume_ratio(df: pd.DataFrame, window: int = 20) -> dict:
    """
    Volume ratio vs 20-day average.
    Confirms strength of price move — high volume = conviction.

    Returns:
        ratio: current volume / 20-day average (1.0 = average)
        above_average: True if ratio > 1.5 (significant volume)
    """
    vol_avg = float(df["Volume"].rolling(window).mean().iloc[-1])
    current_vol = float(df["Volume"].iloc[-1])

    ratio = current_vol / vol_avg if vol_avg > 0 else 1.0

    return {
        "ratio": round(ratio, 2),
        "above_average": ratio > 1.5,
        "current": int(current_vol),
        "average": int(vol_avg),
    }
