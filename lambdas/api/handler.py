"""
AlphaForge — API Lambda (read-only)
Serves signal data to the Web Dashboard via API Gateway.

Routes:
  GET /signals/latest          → latest signal for all symbols
  GET /signals/{symbol}        → history for a specific symbol
  GET /summary                 → score summary across watchlist
"""
import json
import logging
import os
from typing import Any

import boto3
from boto3.dynamodb.conditions import Key

logger = logging.getLogger()
logger.setLevel(logging.INFO)

DYNAMODB_TABLE = os.environ.get("DYNAMODB_TABLE", "alpha-signals")
WATCHLIST = os.environ.get("WATCHLIST", "AAPL,MSFT,NVDA,GOOGL,TSLA,SPY").split(",")

dynamodb = boto3.resource("dynamodb", region_name="us-east-1")

CORS_HEADERS = {
    "Content-Type": "application/json",
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Methods": "GET,OPTIONS",
}


def _ok(body: Any) -> dict:
    return {"statusCode": 200, "headers": CORS_HEADERS, "body": json.dumps(body)}


def _err(status: int, message: str) -> dict:
    return {"statusCode": status, "headers": CORS_HEADERS, "body": json.dumps({"error": message})}


def _get_latest_signals() -> list[dict]:
    """Get the most recent signal for each symbol in watchlist."""
    table = dynamodb.Table(DYNAMODB_TABLE)
    results = []
    for symbol in WATCHLIST:
        response = table.query(
            KeyConditionExpression=Key("symbol").eq(symbol),
            ScanIndexForward=False,
            Limit=1,
        )
        if response["Items"]:
            results.append(response["Items"][0])
    return results


def _get_symbol_history(symbol: str, limit: int = 30) -> list[dict]:
    """Get signal history for a specific symbol (up to 30 records)."""
    table = dynamodb.Table(DYNAMODB_TABLE)
    response = table.query(
        KeyConditionExpression=Key("symbol").eq(symbol),
        ScanIndexForward=False,
        Limit=limit,
    )
    return response["Items"]


def lambda_handler(event: dict, context: Any) -> dict:
    path = event.get("path", "/")
    method = event.get("httpMethod", "GET")
    path_params = event.get("pathParameters") or {}

    logger.info({"action": "api_request", "path": path, "method": method})

    if method == "OPTIONS":
        return {"statusCode": 200, "headers": CORS_HEADERS, "body": ""}

    try:
        if path == "/signals/latest":
            signals = _get_latest_signals()
            return _ok({"signals": signals, "count": len(signals)})

        elif path.startswith("/signals/") and path_params.get("symbol"):
            symbol = path_params["symbol"].upper()
            if symbol not in WATCHLIST:
                return _err(404, f"Symbol {symbol} not in watchlist")
            history = _get_symbol_history(symbol)
            return _ok({"symbol": symbol, "history": history, "count": len(history)})

        elif path == "/summary":
            signals = _get_latest_signals()
            summary = {
                "total": len(signals),
                "by_signal": {},
                "avg_score": 0.0,
            }
            for s in signals:
                sig = s.get("signal", "UNKNOWN")
                summary["by_signal"][sig] = summary["by_signal"].get(sig, 0) + 1
            if signals:
                scores = [float(s.get("score", 0)) for s in signals]
                summary["avg_score"] = round(sum(scores) / len(scores), 3)
            return _ok(summary)

        else:
            return _err(404, f"Route not found: {path}")

    except Exception as e:
        logger.error({"action": "api_error", "path": path, "error": str(e)})
        return _err(500, "Internal server error")
