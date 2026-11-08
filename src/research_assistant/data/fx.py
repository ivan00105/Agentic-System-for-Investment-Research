"""Exchange rates into US dollars from the first configured provider that has the currency (REFERENCE §10).

A year's flows convert at the average of its daily rates and a balance at the rate on its date (as in ASC 830 and
IAS 21). One rate always comes from one provider; a skipped or failed provider is noted, and a fallback is labelled.
"""
import os
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

from .. import config
from ..finance import currency as maths
from . import fx_frankfurter, fx_fred
from .cache import DiskCache
from .errors import DataError

ADAPTERS = {module.NAME: module for module in (fx_fred, fx_frankfurter)}


@dataclass(frozen=True)
class Rate:
    currency: str
    per_usd: Decimal  # units of the currency per US dollar
    basis: str  # "average" (a period's flows) or "year_end" (a balance)
    first: date  # the first and last day whose rates were used
    last: date
    days: int
    source: str  # the provider's label, "(fallback)" when a provider before it was skipped
    url: str
    series: str | None
    notes: tuple[str, ...] = ()  # providers skipped or failed on the way


def provider_order() -> list[str]:
    """Names in priority order: FX_PROVIDERS in the environment, else config.FX_PROVIDERS."""
    raw = os.getenv("FX_PROVIDERS", "").strip()
    names = [n.strip().lower() for n in raw.split(",") if n.strip()] if raw else list(config.FX_PROVIDERS)
    return [n for n in names if n in ADAPTERS]


def having(currency: str, names: list[str] | None = None) -> list[str]:
    return [n for n in (names if names is not None else provider_order()) if currency in ADAPTERS[n].SERIES]


def _rate(currency: str, start: date, end: date, basis: str, cache: DiskCache, names: list[str] | None) -> Rate:
    slack = timedelta(days=config.FX_WINDOW_SLACK_DAYS)
    candidates, notes, errors = having(currency, names), [], []
    if not candidates:
        raise DataError(f"No exchange-rate provider has {currency}.", "not_found")
    for name in candidates:
        adapter = ADAPTERS[name]
        if not adapter.configured():
            notes.append(f"{adapter.LABEL} skipped: not configured (set {', '.join(adapter.ENV)}).")
            continue
        try:
            rows = adapter.fetch(currency, start, end, cache)
        except DataError as exc:
            errors.append(exc)
            notes.append(f"{adapter.LABEL} failed: {exc}")
            continue
        first, last = date.fromisoformat(rows[0]["date"]), date.fromisoformat(rows[-1]["date"])
        if (basis == "average" and first > start + slack) or last < end - slack:
            notes.append(f"{adapter.LABEL} has {currency} rates only from {first} to {last}.")
            continue
        used = rows if basis == "average" else rows[-1:]
        label = adapter.LABEL + ("" if name == candidates[0] else " (fallback)")
        return Rate(currency, maths.mean([Decimal(r["value"]) for r in used]), basis,
                    date.fromisoformat(used[0]["date"]), last, len(used), label, adapter.url(currency),
                    adapter.series(currency), tuple(notes))
    raise DataError(f"No {currency} rate for {start} to {end}: {' '.join(notes)}",
                    "network" if errors and any(e.code != "not_found" for e in errors) else "not_found")


def average(currency: str, start: date, end: date, cache: DiskCache, names: list[str] | None = None) -> Rate:
    """The mean of the daily rates from start to end: for a fiscal year's income and cash flow."""
    return _rate(currency, start, end, "average", cache, names)


def at(currency: str, day: date, cache: DiskCache, names: list[str] | None = None) -> Rate:
    """The last daily rate on or before `day`: for a balance at a fiscal year end."""
    return _rate(currency, day - timedelta(days=config.FX_WINDOW_SLACK_DAYS), day, "year_end", cache, names)
