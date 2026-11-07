"""Frankfurter (tier 0: no key): the European Central Bank's daily reference rates, crossed into US dollars.
https://frankfurter.dev/ . ECB rates are set once a day and never revised. It has CNY and HKD but not TWD.
"""
import json
import tempfile
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import httpx

from .. import config
from . import http
from .cache import DiskCache
from .errors import DataError

NAME, TIER, ENV, LABEL = "frankfurter", 0, (), "Frankfurter (ECB reference rates)"
NOTE = "ECB daily reference rates for about 30 currencies, including CNY and HKD but not TWD."
API = "https://api.frankfurter.dev/v1/"
SERIES = {code: None for code in (
    "AUD", "BRL", "CAD", "CHF", "CNY", "CZK", "DKK", "EUR", "GBP", "HKD", "HUF", "IDR", "ILS", "INR", "ISK", "JPY",
    "KRW", "MXN", "MYR", "NOK", "NZD", "PHP", "PLN", "RON", "SEK", "SGD", "THB", "TRY", "ZAR")}
transport: httpx.BaseTransport | None = None  # tests replace this; production uses the network


def configured() -> bool:
    return True


def _get(path: str, params: dict, cache: DiskCache, max_age: timedelta | None) -> dict:
    key = f"frankfurter|{path}|{json.dumps(params, sort_keys=True)}"
    cached = cache.get(key, max_age)
    if cached is not None:
        return json.loads(cached[0])
    body = http.get(API + path, params, "Frankfurter", transport=transport).content
    try:
        payload = json.loads(body)
    except ValueError as exc:
        raise DataError("Frankfurter returned something other than JSON.", "bad_data") from exc
    cache.put(key, body, datetime.now(timezone.utc))
    return payload


def fetch(currency: str, start: date, end: date, cache: DiskCache) -> list[dict]:
    """Daily rates in date order, {"date", "value"}, as units of the currency per US dollar."""
    final = end < date.today() - timedelta(days=config.FX_FINAL_AFTER_DAYS)
    payload = _get(f"{start.isoformat()}..{end.isoformat()}", {"base": "USD", "symbols": currency}, cache,
                   None if final else timedelta(hours=config.FX_CACHE_MAX_AGE_HOURS))
    # The answer starts on the last rate before `start`, so days outside the period are left out.
    rows = [{"date": day, "value": str(rates[currency])} for day, rates in sorted(payload.get("rates", {}).items())
            if currency in rates and start.isoformat() <= day <= end.isoformat()]
    if not rows:
        raise DataError(f"Frankfurter has no {currency} rates between {start} and {end}.", "not_found")
    return rows


def url(currency: str) -> str:
    return "https://frankfurter.dev/"


def series(currency: str) -> None:
    return None


def check() -> str:
    with tempfile.TemporaryDirectory() as folder:  # a throwaway cache, so the check really reaches Frankfurter
        payload = _get("latest", {"base": "USD", "symbols": "CNY"}, DiskCache(Path(folder)), None)
    return f"Frankfurter answered: {payload.get('rates', {}).get('CNY')} CNY per US dollar on {payload.get('date')}."
