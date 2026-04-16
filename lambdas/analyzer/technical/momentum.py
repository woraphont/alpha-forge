"""
AlphaForge — Momentum Indicators
RSI (14) + MACD histogram
"""
import logging

import pandas as pd

logger = logging.getLogger(__name__)


def calculate_rsi(df: pd.DataFrame, period: int = 14) -> dict:
    """
    RSI scoring.

    Score:
        +0.10 → RSI < 30 (oversold — potential reversal up)
        +0.05 → RSI 30–45 (recovery zone)
         0.00 → RSI 45–65 (neutral)
        -0.05 → RSI > 70 (overbought — caution)
    """
    close = df["Close"]
    delta = close.diff()
    gain = delta.clip(lower=0).ewm(span=period, adjust=False).mean()
    loss = (-delta.clip(upper=0)).ewm(span=period, adjust=False).mean()

    rs = gain / loss.replace(0, float("nan"))
    rsi = 100 - (100 / (1 + rs))
    current_rsi = float(rsi.iloc[-1])

    if current_rsi < 30:
        score, signal = 0.10, "OVERSOLD"
    elif current_rsi <= 45:
        score, signal = 0.05, "RECOVERY_ZONE"
    elif current_rsi >= 70:
        score, signal = -0.05, "OVERBOUGHT"
    else:
        score, signal = 0.00, "NEUTRAL"

    return {"score": score, "signal": signal, "rsi": round(current_rsi, 2)}


def calculate_macd(df: pd.DataFrame, fast: int = 12, slow: int = 26, signal: int = 9) -> dict:
    """
    MACD histogram scoring — uses histogram slope for early detection.

    Score:
        +0.10 → Bullish zero-cross (histogram prev < 0, curr > 0)
        +0.05 → Histogram rising (bullish momentum building)
        -0.10 → Bearish zero-cross (histogram prev > 0, curr < 0)
        -0.05 → Histogram falling
         0.00 → Neutral
    """
    close = df["Close"]
    ema_fast = close.ewm(span=fast, adjust=False).mean()
    ema_slow = close.ewm(span=slow, adjust=False).mean()
    macd_line = ema_fast - ema_slow
    signal_line = macd_line.ewm(span=signal, adjust=False).mean()
    histogram = macd_line - signal_line

    prev_hist = float(histogram.iloc[-2])
    curr_hist = float(histogram.iloc[-1])

    if prev_hist < 0 and curr_hist > 0:
        score, sig = 0.10, "BULLISH_CROSS"
    elif prev_hist > 0 and curr_hist < 0:
        score, sig = -0.10, "BEARISH_CROSS"
    elif curr_hist > prev_hist and curr_hist > 0:
        score, sig = 0.05, "HISTOGRAM_RISING"
    elif curr_hist < prev_hist and curr_hist < 0:
        score, sig = -0.05, "HISTOGRAM_FALLING"
    else:
        score, sig = 0.00, "NEUTRAL"

    return {
        "score": score,
        "signal": sig,
        "histogram": round(curr_hist, 4),
        "macd_line": round(float(macd_line.iloc[-1]), 4),
        "signal_line": round(float(signal_line.iloc[-1]), 4),
    }
