"""
AlphaForge — Telegram Interactive Handler
User sends any US ticker → bot analyzes → sends result back instantly.
Supports all US stocks via yfinance (NYSE, NASDAQ, AMEX).
"""
import json
import logging
import re
from typing import Any

import boto3
import requests
import yfinance as yf

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

_TELEGRAM_API = "https://api.telegram.org/bot{token}/sendMessage"
_SSM_CLIENT = None
_VALID_TICKER = re.compile(r"^[A-Z]{1,5}(-[A-Z])?$")   # AAPL, BRK-B


# ───── AWS HELPERS ─────

def _ssm() -> Any:
    global _SSM_CLIENT
    if _SSM_CLIENT is None:
        _SSM_CLIENT = boto3.client("ssm", region_name="us-east-1")
    return _SSM_CLIENT


def _get_secret(name: str) -> str:
    """Fetch secret from SSM Parameter Store."""
    resp = _ssm().get_parameter(Name=name, WithDecryption=True)
    return resp["Parameter"]["Value"]


# ───── TELEGRAM HELPERS ─────

def _send(token: str, chat_id: int | str, text: str) -> None:
    """Send HTML message to Telegram user."""
    requests.post(
        _TELEGRAM_API.format(token=token),
        json={"chat_id": chat_id, "text": text, "parse_mode": "HTML"},
        timeout=10,
    )


# ───── ANALYSIS ─────

def _analyze(symbol: str) -> dict:
    """Fetch OHLCV and compute technical indicators for any US ticker."""
    ticker = yf.Ticker(symbol)
    df = ticker.history(period="60d", interval="1d")

    if df is None or df.empty:
        raise ValueError(f"No market data for {symbol}")

    close = df["Close"]
    volume = df["Volume"]

    # Price
    price = round(float(close.iloc[-1]), 2)
    change_pct = round(float((close.iloc[-1] - close.iloc[-2]) / close.iloc[-2] * 100), 2)

    # EMA 20 / 50
    ema20 = float(close.ewm(span=20).mean().iloc[-1])
    ema50 = float(close.ewm(span=50).mean().iloc[-1])
    ema_bull = ema20 > ema50

    # RSI 14
    delta = close.diff()
    gain = delta.clip(lower=0).rolling(14).mean()
    loss = (-delta.clip(upper=0)).rolling(14).mean()
    rsi = round(float(100 - (100 / (1 + gain.iloc[-1] / loss.iloc[-1]))), 1)

    # MACD (12/26/9)
    macd_line = close.ewm(span=12).mean() - close.ewm(span=26).mean()
    signal_line = macd_line.ewm(span=9).mean()
    macd_bull = float(macd_line.iloc[-1]) > float(signal_line.iloc[-1])

    # VWAP (20-day proxy)
    vwap = float((close * volume).rolling(20).sum() / volume.rolling(20).sum().iloc[-1])
    vwap_above = price > vwap

    # Volume ratio vs 20-day avg
    avg_vol = float(volume.rolling(20).mean().iloc[-1])
    vol_ratio = round(float(volume.iloc[-1]) / avg_vol, 2) if avg_vol > 0 else 1.0

    # Scoring
    score = sum([
        0.25 if ema_bull else 0.0,
        0.20 if 40 < rsi < 70 else 0.0,
        0.20 if macd_bull else 0.0,
        0.15 if vwap_above else 0.0,
        0.10 if change_pct > 0 else 0.0,
        0.10 if vol_ratio > 1.2 else 0.0,
    ])
    score = round(score, 3)

    if score >= 0.75:
        signal = "STRONG_BUY"
    elif score >= 0.55:
        signal = "BUY"
    elif score >= 0.35:
        signal = "WATCH"
    else:
        signal = "NEUTRAL"

    # Company name
    info = ticker.info
    company = info.get("shortName") or info.get("longName") or symbol

    return {
        "symbol": symbol,
        "company": company,
        "price": price,
        "change_pct": change_pct,
        "score": score,
        "signal": signal,
        "rsi": rsi,
        "ema_bull": ema_bull,
        "macd_bull": macd_bull,
        "vwap_above": vwap_above,
        "vol_ratio": vol_ratio,
    }


# ───── FORMATTING ─────

def _format(r: dict) -> str:
    """Format analysis result as Telegram HTML."""
    emoji_map = {"STRONG_BUY": "🚀", "BUY": "📈", "WATCH": "👀", "NEUTRAL": "➖"}
    emoji = emoji_map.get(r["signal"], "📊")
    change_icon = "🟢" if r["change_pct"] >= 0 else "🔴"
    change_str = f"{'+' if r['change_pct'] >= 0 else ''}{r['change_pct']}%"

    rsi_note = ""
    if r["rsi"] > 70:
        rsi_note = " ⚠️ Overbought"
    elif r["rsi"] < 30:
        rsi_note = " ⚠️ Oversold"

    lines = [
        f"{emoji} <b>{r['symbol']}</b> — {r['company']}",
        "",
        f"💵 ${r['price']}  {change_icon} {change_str}",
        "",
        f"Signal: <code>{r['signal']}</code>",
        f"Score:  <code>{r['score']:.3f}</code>",
        "",
        "<b>Indicators:</b>",
        f"• EMA 20/50: {'Bullish ✅' if r['ema_bull'] else 'Bearish ❌'}",
        f"• RSI 14:    <code>{r['rsi']}</code>{rsi_note}",
        f"• MACD:      {'Bullish ✅' if r['macd_bull'] else 'Bearish ❌'}",
        f"• VWAP:      {'Above ✅' if r['vwap_above'] else 'Below ❌'}",
        f"• Volume:    <code>{r['vol_ratio']}x</code> avg",
        "",
        f'🔗 <a href="https://www.tradingview.com/chart/?symbol={r["symbol"]}">TradingView Chart</a>',
    ]
    return "\n".join(lines)


_HELP_TEXT = (
    "👋 <b>AlphaForge Bot</b>\n\n"
    "พิมพ์ ticker หุ้น US เพื่อวิเคราะห์ทันที\n\n"
    "ตัวอย่าง:\n"
    "<code>AAPL</code>  <code>NVDA</code>  <code>TSLA</code>\n"
    "<code>META</code>  <code>SPY</code>   <code>QQQ</code>\n"
    "<code>AMD</code>   <code>PLTR</code>  <code>BRK-B</code>"
)


# ───── LAMBDA HANDLER ─────

def handler(event: dict, context: Any) -> dict:
    """Telegram webhook entry point."""
    token: str | None = None
    chat_id: int | str | None = None
    symbol = ""

    try:
        body = json.loads(event.get("body") or "{}")
        message = body.get("message", {})
        chat_id = message.get("chat", {}).get("id")
        text = (message.get("text") or "").strip().upper()

        if not chat_id or not text:
            return {"statusCode": 200, "body": "ok"}

        token = _get_secret("/alpha-forge/TELEGRAM_BOT_TOKEN")

        # Commands
        if text in ("/START", "/HELP"):
            _send(token, chat_id, _HELP_TEXT)
            return {"statusCode": 200, "body": "ok"}

        # Validate ticker
        if not _VALID_TICKER.match(text):
            _send(token, chat_id,
                f"❌ <code>{text}</code> ไม่ใช่ ticker ที่ถูกต้อง\n"
                "ตัวอย่าง: <code>AAPL</code>, <code>NVDA</code>, <code>BRK-B</code>")
            return {"statusCode": 200, "body": "ok"}

        symbol = text
        _send(token, chat_id, f"⏳ กำลังวิเคราะห์ <b>{symbol}</b>...")

        result = _analyze(symbol)
        _send(token, chat_id, _format(result))

        logger.info({"action": "analyzed", "symbol": symbol, "signal": result["signal"]})

    except ValueError as e:
        logger.warning({"action": "not_found", "symbol": symbol, "error": str(e)})
        if token and chat_id:
            _send(token, chat_id,
                f"❌ ไม่พบข้อมูลของ <b>{symbol}</b>\n"
                "ตรวจสอบ ticker อีกครั้ง หรือหุ้นอาจ delisted แล้ว")

    except Exception as e:
        logger.error({"action": "error", "symbol": symbol, "error": str(e)})
        if token and chat_id:
            _send(token, chat_id, "❌ เกิดข้อผิดพลาด กรุณาลองใหม่อีกครั้ง")

    return {"statusCode": 200, "body": "ok"}
