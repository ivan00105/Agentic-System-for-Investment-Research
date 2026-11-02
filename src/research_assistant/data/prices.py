"""Daily prices from the first configured provider in config order, with labelled fallback (REFERENCE §10).

Every row carries the as-traded `close` (for market cap) and the split- and dividend-adjusted `adj_close`
(for returns). One series always comes from one provider.
"""
import json
import os
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from .. import config
from . import prices_tiingo, prices_yfinance
from .cache import DiskCache
from .errors import DataError

ADAPTERS = {module.NAME: module for module in (prices_tiingo, prices_yfinance)}
NEW_YORK = ZoneInfo("America/New_York")


def provider_order() -> list[str]:
    """Names in priority order: PRICE_PROVIDERS in the environment, else config.PRICE_PROVIDERS."""
    raw = os.getenv("PRICE_PROVIDERS", "").strip()
    names = [n.strip().lower() for n in raw.split(",") if n.strip()] if raw else list(config.PRICE_PROVIDERS)
    return [n for n in names if n in ADAPTERS]


def last_known_day(cutoff: datetime) -> date:
    """The latest trading day whose final close was public at the cutoff."""
    local = cutoff.astimezone(NEW_YORK)
    return local.date() if local.hour >= config.PRICE_CLOSE_AVAILABLE_HOUR else local.date() - timedelta(days=1)


def normalize_ticker(ticker: str) -> str:
    return ticker.strip().upper().replace(".", "-")


def fetch(ticker: str, start: date, end: date, cache: DiskCache, names: list[str] | None = None) -> tuple[list[dict], str, list[str]]:
    """Rows in date order, the provider that supplied them, and notes on skipped or failed providers."""
    ticker, notes, errors = normalize_ticker(ticker), [], []
    for name in names if names is not None else provider_order():
        adapter = ADAPTERS[name]
        if not adapter.configured():
            notes.append(f"{name} skipped: not configured (set {', '.join(adapter.ENV)}).")
            continue
        key = f"prices|{name}|{ticker}|{start}|{end}"
        cached = cache.get(key, timedelta(hours=config.PRICE_CACHE_MAX_AGE_HOURS))
        if cached is not None:
            return json.loads(cached[0]), name, notes
        try:
            rows = adapter.fetch(ticker, start, end)
        except DataError as exc:
            errors.append(exc)
            notes.append(f"{name} failed: {exc}")
            continue
        cache.put(key, json.dumps(rows).encode(), datetime.now(timezone.utc))
        return rows, name, notes
    if errors and all(e.code == "not_found" for e in errors):
        raise DataError(f"No price history for {ticker}. " + " ".join(notes), "not_found")
    raise DataError(f"No price provider could supply {ticker}. " + " ".join(notes), "not_configured" if not errors else "network")
