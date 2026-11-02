"""Tiingo end-of-day prices (tier 1: free key). Raw and adjusted closes, dividends and split factors.
https://www.tiingo.com/documentation/end-of-day
"""
import os
import time
from datetime import date

import httpx

from .. import config
from .errors import DataError

NAME, TIER, ENV, LABEL = "tiingo", 1, ("TIINGO_API_KEY",), "Tiingo"
URL = "https://api.tiingo.com/tiingo/daily/{ticker}/prices"
RETRY_STATUSES = {429, 500, 502, 503, 504}
transport: httpx.BaseTransport | None = None  # tests replace this; production uses the network


def configured() -> bool:
    return bool(os.getenv("TIINGO_API_KEY", "").strip())


def _get(url: str, params: dict, sleep=time.sleep):
    headers = {"Authorization": f"Token {os.getenv('TIINGO_API_KEY', '').strip()}", "Content-Type": "application/json"}
    attempts = config.HTTP_RETRIES + 1
    with httpx.Client(transport=transport, timeout=config.HTTP_TIMEOUT_SECONDS) as client:
        for attempt in range(attempts):
            if attempt:
                sleep(config.HTTP_RETRY_BACKOFF_SECONDS * 2 ** (attempt - 1))
            try:
                response = client.get(url, params=params, headers=headers)
            except httpx.TransportError as exc:
                if attempt == attempts - 1:
                    raise DataError(f"Tiingo did not respond: {exc}", "network") from exc
                continue
            if response.status_code in RETRY_STATUSES and attempt < attempts - 1:
                continue
            if response.status_code == 404:
                raise DataError("Tiingo has no such ticker.", "not_found", 404)
            if response.status_code != 200:
                raise DataError(f"Tiingo returned HTTP {response.status_code}.", "http_error", response.status_code)
            return response.json()


def fetch(ticker: str, start: date, end: date) -> list[dict]:
    rows = _get(URL.format(ticker=ticker), {"startDate": start.isoformat(), "endDate": end.isoformat()})
    if not isinstance(rows, list):
        raise DataError("Tiingo returned an unexpected response.", "bad_data")
    if not rows:
        raise DataError(f"Tiingo has no prices for {ticker} between {start} and {end}.", "not_found")
    return [{"date": r["date"][:10], "close": r.get("close"), "adj_close": r.get("adjClose"), "volume": r.get("volume"),
             "dividend": r.get("divCash", 0.0), "split": r.get("splitFactor", 1.0)} for r in rows]


def check() -> str:
    _get("https://api.tiingo.com/api/test", {})
    return "Tiingo accepted the API key."
