"""Finnhub earnings and dividend calendars (tier 1: requires FINNHUB_API_KEY)."""
import json
import os
from pathlib import Path
import tempfile
from datetime import date, datetime, timedelta, timezone

from . import http
from .cache import DiskCache
from .errors import DataError

NAME, TIER, ENV, LABEL = "finnhub", 1, ("FINNHUB_API_KEY",), "Finnhub calendars"
API = "https://finnhub.io/api/v1"
transport = None


def configured() -> bool:
    return bool(os.getenv("FINNHUB_API_KEY", "").strip())


def _get(path: str, params: dict, cache: DiskCache) -> dict:
    secret = os.getenv("FINNHUB_API_KEY", "").strip()
    key = f"finnhub|{path}|{json.dumps(params, sort_keys=True)}"
    cached = cache.get(key, None)
    if cached is not None:
        return json.loads(cached[0])
    body = http.get(API + path, params, "Finnhub", headers={"X-Finnhub-Token": secret},
                    transport=transport, secret=secret).content
    try:
        payload = json.loads(body)
    except ValueError as exc:
        raise DataError("Finnhub returned something other than JSON.", "bad_data") from exc
    cache.put(key, body, datetime.now(timezone.utc))
    return payload


def fetch(ticker: str, start: date, end: date, cache: DiskCache) -> list[dict]:
    rows = []
    try:
        earnings = _get("/calendar/earnings", {"from": start.isoformat(), "to": end.isoformat(), "symbol": ticker}, cache)
        for row in earnings.get("earningsCalendar", []) or []:
            found = row.get("date")
            if found:
                rows.append({"kind": "earnings", "date": found,
                             "status": "occurred" if found < date.today().isoformat() else "upcoming",
                             "details": {"eps_estimate": str(row["epsEstimate"])}
                             if row.get("epsEstimate") is not None else {}, "source": "finnhub"})
    except DataError:
        pass
    try:
        dividends = _get("/stock/dividend2", {"symbol": ticker, "from": start.isoformat(), "to": end.isoformat()}, cache)
        payload = dividends.get("dividends") if isinstance(dividends, dict) else dividends
        for row in payload or []:
            found = row.get("exDate") or row.get("exDividendDate")
            if found:
                amount = row.get("amount") or row.get("dividend")
                details = {"amount": str(amount)} if amount is not None else {}
                rows.append({"kind": "ex_dividend", "date": found,
                             "status": "occurred" if found < date.today().isoformat() else "upcoming",
                             "details": details, "source": "finnhub"})
    except DataError:
        pass
    if not rows:
        raise DataError(f"Finnhub returned no earnings or ex-dividend dates for {ticker}.", "not_found")
    return rows


def check() -> str:
    with tempfile.TemporaryDirectory() as folder:
        fetch("SPY", date.today(), date.today() + timedelta(days=31),
              DiskCache(Path(folder)))
    return "Finnhub returned a market calendar."
