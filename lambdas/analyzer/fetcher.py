"""
AlphaForge — Data Fetcher
Fetches OHLCV price data + news headlines for US stocks via yfinance.
Phase 2: upgrade news to Alpaca News API.
"""
import logging
from typing import Any

import pandas as pd
import yfinance as yf

logger = logging.getLogger(__name__)


def fetch_stock_data(symbol: str, period: str = "3mo", interval: str = "1d") -> pd.DataFrame:
    """
    Fetch OHLCV data for a US stock symbol.

    Args:
        symbol: Ticker symbol (e.g. "AAPL")
        period: Lookback period ("3mo", "6mo", "1y")
        interval: Bar interval ("1d", "4h", "1h")

    Returns:
        DataFrame with columns: Open, High, Low, Close, Volume

    Raises:
        ValueError: If no data returned (market closed, invalid symbol)
    """
    ticker = yf.Ticker(symbol)
    df = ticker.history(period=period, interval=interval, auto_adjust=True)

    if df.empty:
        raise ValueError(f"No price data for {symbol} (period={period}, interval={interval})")

    df.index = pd.to_datetime(df.index)
    logger.info({"action": "fetch_price", "symbol": symbol, "rows": len(df), "period": period})
    return df


def fetch_stock_info(symbol: str) -> dict[str, Any]:
    """
    Fetch basic fundamentals (market cap, sector, PE ratio).
    Used for context in LLM pattern analysis (Phase 2+).
    """
    ticker = yf.Ticker(symbol)
    info = ticker.info
    return {
        "symbol": symbol,
        "name": info.get("longName", symbol),
        "sector": info.get("sector", "Unknown"),
        "market_cap": info.get("marketCap", 0),
        "pe_ratio": info.get("trailingPE", None),
        "52w_high": info.get("fiftyTwoWeekHigh", None),
        "52w_low": info.get("fiftyTwoWeekLow", None),
    }


def fetch_news(symbol: str, max_items: int = 5) -> list[dict[str, str]]:
    """
    Fetch recent news headlines for a symbol via yfinance (free, no API key).
    Phase 2: replace/supplement with Alpaca News API for better quality.

    Returns:
        List of dicts with keys: title, publisher, link
    """
    try:
        ticker = yf.Ticker(symbol)
        raw_news = ticker.news or []
        news = [
            {
                "title": item.get("title", ""),
                "publisher": item.get("publisher", ""),
                "link": item.get("link", ""),
            }
            for item in raw_news[:max_items]
        ]
        logger.info({"action": "fetch_news", "symbol": symbol, "count": len(news)})
        return news
    except Exception as e:
        logger.warning({"action": "fetch_news_failed", "symbol": symbol, "error": str(e)})
        return []


def fetch_options_pcr(symbol: str) -> float:
    """
    Calculate Put/Call Ratio from yfinance options chain (free).
    PCR < 0.7 = bullish, > 1.0 = bearish.

    Returns:
        PCR float, or 1.0 (neutral) if options data unavailable.
    """
    try:
        ticker = yf.Ticker(symbol)
        expirations = ticker.options
        if not expirations:
            return 1.0

        # Use nearest expiration
        opt = ticker.option_chain(expirations[0])
        total_put_oi = opt.puts["openInterest"].sum()
        total_call_oi = opt.calls["openInterest"].sum()

        if total_call_oi == 0:
            return 1.0

        pcr = total_put_oi / total_call_oi
        logger.info({"action": "fetch_pcr", "symbol": symbol, "pcr": round(pcr, 3)})
        return round(pcr, 3)
    except Exception as e:
        logger.warning({"action": "fetch_pcr_failed", "symbol": symbol, "error": str(e)})
        return 1.0
