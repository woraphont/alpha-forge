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
    Supertrend indicator — stateful ATR-based dynamic trend direction.

    Uses carry-forward logic: upper band only moves down, lower band only moves up.
    Trend flips when close crosses above upper band (→ bull) or below lower band (→ bear).

    Score:
        +0.10 → direction == 1  (bullish — price above support band)
         0.0  → direction == -1 (bearish — price below resistance band)

    Returns dict with keys: score, direction ("UP"/"DOWN"), support, resistance, atr
    """
    high = df["High"]
    low = df["Low"]
    close = df["Close"]

    # True Range (uses previous close)
    prev_close = close.shift(1)
    tr = pd.concat([
        high - low,
        (high - prev_close).abs(),
        (low - prev_close).abs(),
    ], axis=1).max(axis=1)

    atr = tr.ewm(span=period, adjust=False).mean()
    hl2 = (high + low) / 2
    upper_basic = hl2 + multiplier * atr
    lower_basic = hl2 - multiplier * atr

    # Stateful carry-forward bands + direction
    upper = upper_basic.copy().astype(float)
    lower = lower_basic.copy().astype(float)
    direction = pd.Series(1, index=close.index)   # 1=bull, -1=bear

    for i in range(1, len(close)):
        # Upper band: only moves DOWN (tightens resistance)
        if close.iat[i - 1] <= upper.iat[i - 1]:
            upper.iat[i] = min(upper_basic.iat[i], upper.iat[i - 1])
        else:
            upper.iat[i] = upper_basic.iat[i]

        # Lower band: only moves UP (raises support floor)
        if close.iat[i - 1] >= lower.iat[i - 1]:
            lower.iat[i] = max(lower_basic.iat[i], lower.iat[i - 1])
        else:
            lower.iat[i] = lower_basic.iat[i]

        # Direction: flip on cross
        if direction.iat[i - 1] == -1 and close.iat[i] > upper.iat[i - 1]:
            direction.iat[i] = 1    # flip to bull
        elif direction.iat[i - 1] == 1 and close.iat[i] < lower.iat[i - 1]:
            direction.iat[i] = -1   # flip to bear
        else:
            direction.iat[i] = direction.iat[i - 1]

    is_bullish = bool(direction.iloc[-1] == 1)
    dir_str = "UP" if is_bullish else "DOWN"
    score = 0.10 if is_bullish else -0.10

    current_atr = float(atr.iloc[-1])
    current_lower = float(lower.iloc[-1])
    current_upper = float(upper.iloc[-1])

    return {
        "score": score,
        "direction": dir_str,
        "support": round(current_lower, 2),
        "resistance": round(current_upper, 2),
        "atr": round(current_atr, 2),
    }
