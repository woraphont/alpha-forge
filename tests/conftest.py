"""
AlphaForge — pytest configuration and shared fixtures.
"""
import pandas as pd
import numpy as np
import pytest


def make_ohlcv(n: int = 100, trend: str = "bull") -> pd.DataFrame:
    """
    Generate synthetic OHLCV data for testing.

    Args:
        n: Number of bars
        trend: "bull", "bear", or "flat"
    """
    np.random.seed(42)
    base = 150.0

    if trend == "bull":
        prices = base + np.cumsum(np.random.normal(0.3, 1.5, n))
    elif trend == "bear":
        prices = base + np.cumsum(np.random.normal(-0.3, 1.5, n))
    else:
        prices = base + np.cumsum(np.random.normal(0, 1.0, n))

    prices = np.abs(prices)  # no negative prices
    high = prices * (1 + np.abs(np.random.normal(0, 0.005, n)))
    low = prices * (1 - np.abs(np.random.normal(0, 0.005, n)))
    volume = np.random.randint(1_000_000, 10_000_000, n)

    index = pd.date_range("2024-01-01", periods=n, freq="B")
    return pd.DataFrame({
        "Open": prices * (1 + np.random.normal(0, 0.002, n)),
        "High": high,
        "Low": low,
        "Close": prices,
        "Volume": volume,
    }, index=index)


@pytest.fixture
def bull_df() -> pd.DataFrame:
    return make_ohlcv(n=250, trend="bull")


@pytest.fixture
def bear_df() -> pd.DataFrame:
    return make_ohlcv(n=250, trend="bear")


@pytest.fixture
def flat_df() -> pd.DataFrame:
    return make_ohlcv(n=250, trend="flat")


@pytest.fixture
def sample_news() -> list[dict]:
    return [
        {"title": "NVDA beats earnings expectations, stock surges 8%", "publisher": "Reuters", "link": ""},
        {"title": "Federal Reserve signals rate cut in September", "publisher": "WSJ", "link": ""},
    ]
