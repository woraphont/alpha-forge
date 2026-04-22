"""
AlphaForge — Notifier
Sends Telegram alerts for high-confidence signals.
Secrets fetched from SSM Parameter Store (never hardcoded).
"""
import logging
from typing import Any

import boto3
import requests

logger = logging.getLogger(__name__)

_ssm_client = None
_TELEGRAM_API = "https://api.telegram.org/bot{token}/sendMessage"


def _get_ssm_client() -> Any:
    global _ssm_client
    if _ssm_client is None:
        _ssm_client = boto3.client("ssm", region_name="us-east-1")
    return _ssm_client


def _get_secret(param_name: str) -> str:
    """Fetch secret from SSM Parameter Store."""
    client = _get_ssm_client()
    response = client.get_parameter(Name=param_name, WithDecryption=True)
    return response["Parameter"]["Value"]


def _format_telegram_message(symbol: str, result: dict) -> str:
    """Format a Telegram HTML alert message."""
    score = result["score"]
    signal = result["signal"]
    regime = result.get("regime", "UNKNOWN")

    emoji_map = {"STRONG_BUY": "🚀", "BUY": "📈", "WATCH": "👀"}
    emoji = emoji_map.get(signal, "📊")

    ind = result.get("indicators", {})
    rsi_val = ind.get("rsi", {}).get("rsi", "N/A")
    macd_sig = ind.get("macd", {}).get("signal", "N/A")
    trend_sig = ind.get("ema", {}).get("signal", "N/A")
    supertrend = ind.get("supertrend", {}).get("direction", "N/A")
    vwap_above = ind.get("vwap", {}).get("above_vwap", False)
    vwap_label = "Above ✅" if vwap_above else "Below ❌"

    lines = [
        f"{emoji} <b>AlphaForge Signal</b>",
        "",
        f"📊 <b>{symbol}</b>",
        f"Signal: <code>{signal}</code>",
        f"Score:  <code>{score:.3f}</code>",
        f"Regime: <code>{regime}</code>",
        "",
        "<b>Indicators:</b>",
        f"• Trend:      <code>{trend_sig}</code>",
        f"• Supertrend: <code>{supertrend}</code>",
        f"• RSI:        <code>{rsi_val}</code>",
        f"• MACD:       <code>{macd_sig}</code>",
        f"• VWAP:       {vwap_label}",
    ]

    ai_layer = result.get("ai_layer", {})
    finbert_score = ai_layer.get("finbert", 0.5)
    news_label = ai_layer.get("finbert_label", "NEUTRAL")
    lines.append(f"• Sentiment:  <code>{finbert_score:.2f}</code> ({news_label})")

    # Buffett section
    llm_signal = ai_layer.get("llm_signal", "")
    llm_moat = ai_layer.get("llm_moat", "")
    llm_reasoning = ai_layer.get("llm_reasoning", "")
    if llm_reasoning:
        verdict_icon = {"BULLISH": "🟢", "BEARISH": "🔴", "NEUTRAL": "🟡"}.get(llm_signal, "⚪")
        lines += [
            "",
            f'🎩 <b>Buffett\'s Take</b>  {verdict_icon} {llm_signal} | Moat: <code>{llm_moat}</code>',
            f"<i>{llm_reasoning}</i>",
        ]

    return "\n".join(lines)


def send_alert(symbol: str, result: dict) -> None:
    """
    Send Telegram alert for a strong signal.
    Only called when score >= STRONG_BUY_THRESHOLD (0.75).
    """
    try:
        token = _get_secret("/alpha-forge/TELEGRAM_BOT_TOKEN")
        chat_id = _get_secret("/alpha-forge/TELEGRAM_CHAT_ID")
        message = _format_telegram_message(symbol, result)

        response = requests.post(
            _TELEGRAM_API.format(token=token),
            json={
                "chat_id": chat_id,
                "text": message,
                "parse_mode": "HTML",
            },
            timeout=10,
        )

        if response.status_code == 200:
            logger.info({"action": "alert_sent", "symbol": symbol, "score": result["score"]})
        else:
            logger.warning({
                "action": "alert_failed",
                "symbol": symbol,
                "status": response.status_code,
                "body": response.text[:200],
            })

    except Exception as e:
        logger.error({"action": "alert_error", "symbol": symbol, "error": str(e)})
        raise
