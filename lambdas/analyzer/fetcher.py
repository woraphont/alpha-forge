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


def fetch_fundamentals(symbol: str) -> dict[str, Any]:
    """
    Fetch Buffett-style fundamental metrics for a US stock via yfinance.
    Inspired by: github.com/Bilovodskyi/ai-investor (Buffett Algorithm)

    Returns:
        dict with keys: roe, debt_to_equity, operating_margin, current_ratio,
                        net_income, depreciation, capex, owner_earnings,
                        sector, industry, country, beta, pe_ratio,
                        revenue_growth, net_margin
        Missing values are returned as None (not all stocks report all fields).
    """
    try:
        ticker = yf.Ticker(symbol)
        info = ticker.info

        roe = info.get("returnOnEquity")           # e.g. 0.171 = 17.1%
        debt_to_equity = info.get("debtToEquity")  # e.g. 150 = 1.5x (yfinance returns %)
        operating_margin = info.get("operatingMargins")
        current_ratio = info.get("currentRatio")
        net_income = info.get("netIncomeToCommon")
        net_margin = info.get("profitMargins")
        revenue_growth = info.get("revenueGrowth")
        pe_ratio = info.get("trailingPE")
        beta = info.get("beta")
        sector = info.get("sector", "Unknown")
        industry = info.get("industry", "Unknown")
        country = info.get("country", "US")

        # Depreciation + CapEx from cash flow statement
        try:
            cashflow = ticker.cashflow
            depreciation = float(cashflow.loc["Depreciation And Amortization"].iloc[0]) if "Depreciation And Amortization" in cashflow.index else None
            capex = abs(float(cashflow.loc["Capital Expenditure"].iloc[0])) if "Capital Expenditure" in cashflow.index else None
        except Exception:
            depreciation = None
            capex = None

        # Owner Earnings = Net Income + Depreciation - Maintenance CapEx
        # Proxy: maintenance capex ≈ 50% of total capex (conservative)
        owner_earnings = None
        if net_income and depreciation and capex:
            owner_earnings = net_income + depreciation - (capex * 0.5)

        result = {
            "symbol": symbol,
            "roe": roe,
            "debt_to_equity": (debt_to_equity / 100) if debt_to_equity else None,  # normalize to ratio
            "operating_margin": operating_margin,
            "net_margin": net_margin,
            "current_ratio": current_ratio,
            "revenue_growth": revenue_growth,
            "pe_ratio": pe_ratio,
            "beta": beta,
            "sector": sector,
            "industry": industry,
            "country": country,
            "net_income": net_income,
            "depreciation": depreciation,
            "capex": capex,
            "owner_earnings": owner_earnings,
        }
        logger.info({"action": "fetch_fundamentals", "symbol": symbol, "roe": roe, "de": debt_to_equity,
                     "sector": sector, "pe": pe_ratio})
        return result
    except Exception as e:
        logger.warning({"action": "fetch_fundamentals_failed", "symbol": symbol, "error": str(e)})
        return {
            "symbol": symbol, "roe": None, "debt_to_equity": None,
            "operating_margin": None, "net_margin": None, "current_ratio": None,
            "revenue_growth": None, "pe_ratio": None, "beta": None,
            "sector": "Unknown", "industry": "Unknown", "country": "US",
            "net_income": None, "depreciation": None, "capex": None, "owner_earnings": None,
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
