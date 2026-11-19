"""Host-owned event records.

Providers can populate ``ToolContext.records`` with these records without giving the
model authority to create or alter them.  The adapter is intentionally small so
provider-specific calendars can be added without changing the report contract.
"""
import os
from datetime import date, datetime

from .. import config
from . import events_finnhub, events_yfinance
from .cache import DiskCache
from .errors import DataError

from ..contracts import EventRecord

ADAPTERS = {module.NAME: module for module in (events_finnhub, events_yfinance)}


def provider_order() -> list[str]:
    raw = os.getenv("EVENT_PROVIDERS", "").strip()
    names = [n.strip().lower() for n in raw.split(",") if n.strip()] if raw else list(config.EVENT_PROVIDERS)
    return [n for n in names if n in ADAPTERS]


def fetch(ticker: str, start: date, end: date, cutoff: datetime, cache: DiskCache,
          names: list[str] | None = None) -> tuple[list[dict], str, list[str]]:
    """Calendar rows from configured providers, supplemented per missing event type."""
    found: dict[tuple[str, str], dict] = {}
    notes, errors = [], []
    for name in names if names is not None else provider_order():
        adapter = ADAPTERS[name]
        if not adapter.configured():
            notes.append(f"{name} skipped: not configured (set {', '.join(adapter.ENV)}).")
            continue
        try:
            rows = adapter.fetch(ticker, start, end, cache) if name == "finnhub" else adapter.fetch(ticker, start, end)
            for row in rows:
                row["source"] = name
                found.setdefault((row["kind"], row["date"]), row)
        except Exception as exc:
            errors.append(exc)
            notes.append(f"{name} failed: {exc}")
        kinds = {row["kind"] for row in found.values()}
        if {"earnings", "ex_dividend"} <= kinds:
            break
    if not found:
        if not errors:
            raise DataError("No event-calendar provider is configured. Set FINNHUB_API_KEY or use yfinance.",
                            "not_configured")
        raise DataError("No event-calendar provider could supply the calendar. " + " ".join(notes), "network")
    rows = list(found.values())
    source = " + ".join(dict.fromkeys(row["source"] for row in rows))
    return sorted(rows, key=lambda row: (row["date"], row["kind"])), source, notes


def upcoming(
    records: dict[str, dict], ticker: str, as_of: date, observed_before: datetime | None = None
) -> list[EventRecord]:
    result = []
    for data in records.values():
        if data.get("kind") != "event" or data.get("ticker") != ticker:
            continue
        event = EventRecord.model_validate({key: value for key, value in data.items() if key != "kind"})
        if event.event_date >= as_of and (observed_before is None or event.observed_at <= observed_before):
            result.append(event)
    return sorted(result, key=lambda event: (event.event_date, event.id))
