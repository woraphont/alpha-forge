"""
AlphaForge — Analyzer Lambda
Entry point: triggered by EventBridge (09:00 / 09:30 / 16:15 EST MON-FRI)
"""
import json
import logging
import os
import time
from typing import Any

import boto3

from fetcher import fetch_stock_data, fetch_news
from scorer import calculate_score

logger = logging.getLogger()
logger.setLevel(logging.INFO)

WATCHLIST = os.environ.get("WATCHLIST", "AAPL,MSFT,NVDA,GOOGL,TSLA,SPY").split(",")
DYNAMODB_TABLE = os.environ.get("DYNAMODB_TABLE", "alpha-signals")
STRONG_BUY_THRESHOLD = float(os.environ.get("STRONG_BUY_THRESHOLD", "0.75"))
BUY_THRESHOLD = float(os.environ.get("BUY_THRESHOLD", "0.55"))

dynamodb = boto3.resource("dynamodb", region_name="us-east-1")


def _save_signal(symbol: str, result: dict) -> None:
    """Save signal result to DynamoDB with TTL (30 days)."""
    table = dynamodb.Table(DYNAMODB_TABLE)
    ttl = int(time.time()) + (30 * 24 * 3600)
    table.put_item(Item={
        "symbol": symbol,
        "timestamp": result["timestamp"],
        "score": str(result["score"]),
        "signal": result["signal"],
        "indicators": json.dumps(result.get("indicators", {})),
        "ttl": ttl,
    })


def _send_alert_if_needed(symbol: str, result: dict) -> None:
    """Import notifier lazily to avoid import errors in local dev without LINE token."""
    if result["score"] >= STRONG_BUY_THRESHOLD:
        try:
            from notifier import send_alert
            send_alert(symbol, result)
        except Exception as e:
            logger.warning(json.dumps({"action": "alert_failed", "symbol": symbol, "error": str(e)}))


def lambda_handler(event: dict, context: Any) -> dict:
    """Main Lambda handler — analyze all symbols in watchlist."""
    trigger = event.get("source", "manual")
    logger.info(json.dumps({"action": "start", "trigger": trigger, "watchlist": WATCHLIST}))

    results = []
    errors = []

    for symbol in WATCHLIST:
        try:
            df = fetch_stock_data(symbol)
            news = fetch_news(symbol)
            result = calculate_score(symbol, df, news)

            _save_signal(symbol, result)
            _send_alert_if_needed(symbol, result)

            results.append(result)
            logger.info(json.dumps({
                "action": "analyzed",
                "symbol": symbol,
                "score": result["score"],
                "signal": result["signal"],
            }))

        except Exception as e:
            error_msg = {"symbol": symbol, "error": str(e), "type": type(e).__name__}
            errors.append(error_msg)
            logger.error(json.dumps({"action": "error", **error_msg}))

    summary = {
        "analyzed": len(results),
        "errors": len(errors),
        "signals": {r["symbol"]: r["signal"] for r in results},
        "strong_alerts": [r["symbol"] for r in results if r["score"] >= STRONG_BUY_THRESHOLD],
    }
    logger.info(json.dumps({"action": "complete", **summary}))

    return {
        "statusCode": 200,
        "body": json.dumps({"results": results, "errors": errors, "summary": summary}),
    }
