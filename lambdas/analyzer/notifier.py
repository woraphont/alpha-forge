"""
AlphaForge — Notifier
Sends LINE Notify alerts for high-confidence signals.
Secrets fetched from SSM Parameter Store (never hardcoded).
"""
import logging
from typing import Any

import boto3
import requests

logger = logging.getLogger(__name__)

_ssm_client = None


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


def _format_line_message(symbol: str, result: dict) -> str:
    """Format a concise LINE Notify message."""
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

    lines = [
        f"\n{emoji} AlphaForge Signal",
        f"",
        f"📊 {symbol}",
        f"Signal: {signal}",
        f"Score:  {score:.3f}",
        f"Regime: {regime}",
        f"",
        f"Indicators:",
        f"• Trend:      {trend_sig}",
        f"• Supertrend: {supertrend}",
        f"• RSI:        {rsi_val}",
        f"• MACD:       {macd_sig}",
        f"• VWAP:       {'Above ✅' if vwap_above else 'Below ❌'}",
    ]

    ai_layer = result.get("ai_layer", {})
    if ai_layer.get("phase") != "PHASE_1_PLACEHOLDER":
        finbert = ai_layer.get("finbert", 0.5)
        lines.append(f"• FinBERT:    {finbert:.2f}")

    return "\n".join(lines)


def send_alert(symbol: str, result: dict) -> None:
    """
    Send LINE Notify alert for a strong signal.
    Only called when score >= STRONG_BUY_THRESHOLD (0.75).
    """
    try:
        token = _get_secret("/alpha-forge/LINE_NOTIFY_TOKEN")
        message = _format_line_message(symbol, result)

        response = requests.post(
            "https://notify-api.line.me/api/notify",
            headers={"Authorization": f"Bearer {token}"},
            data={"message": message},
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
