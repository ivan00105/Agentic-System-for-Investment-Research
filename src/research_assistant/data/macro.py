"""Macro series and the release calendar from the first configured provider that has them (REFERENCE §10).

One series always comes from one provider. A provider without its key is skipped, and the notes say so.
"""
import os
from datetime import date

from .. import config
from . import macro_fred, macro_treasury
from .cache import DiskCache
from .errors import DataError

ADAPTERS = {module.NAME: module for module in (macro_fred, macro_treasury)}
# Each series in words, and how often it is observed.
SERIES = {
    "tbill_3m": ("3-month T-bill rate", "daily"),
    "treasury_2y": ("2-year Treasury yield", "daily"),
    "treasury_10y": ("10-year Treasury yield", "daily"),
    "fed_funds": ("Fed funds rate", "daily"),
    "cpi_inflation": ("CPI inflation (year on year)", "monthly"),
    "unemployment": ("Unemployment rate", "monthly"),
}


def provider_order() -> list[str]:
    """Names in priority order: MACRO_PROVIDERS in the environment, else config.MACRO_PROVIDERS."""
    raw = os.getenv("MACRO_PROVIDERS", "").strip()
    names = [n.strip().lower() for n in raw.split(",") if n.strip()] if raw else list(config.MACRO_PROVIDERS)
    return [n for n in names if n in ADAPTERS]


def having(series: str, names: list[str] | None = None) -> list[str]:
    """Providers in order that carry the series, configured or not."""
    return [n for n in (names if names is not None else provider_order()) if series in ADAPTERS[n].SERIES]


def needs(series: str) -> list[str]:
    """The settings that would make a series available."""
    return list(dict.fromkeys(env for n in having(series, list(ADAPTERS)) for env in ADAPTERS[n].ENV))


def fetch(series: str, start: date, end: date, as_of: date, cache: DiskCache,
          names: list[str] | None = None) -> tuple[list[dict], str, list[str]]:
    """Observations in date order, the provider that supplied them, and notes on skipped or failed providers."""
    notes, errors = [], []
    for name in having(series, names):
        adapter = ADAPTERS[name]
        if not adapter.configured():
            notes.append(f"{name} skipped: not configured (set {', '.join(adapter.ENV)}).")
            continue
        try:
            return adapter.fetch(series, start, end, as_of, cache), name, notes
        except DataError as exc:
            errors.append(exc)
            notes.append(f"{name} failed: {exc}")
    if errors and all(e.code == "not_found" for e in errors):
        raise DataError(f"No {series} data between {start} and {end}. " + " ".join(notes), "not_found")
    if not errors:
        raise DataError(f"{series} needs {' or '.join(needs(series)) or 'a macro provider'}. " + " ".join(notes),
                        "not_configured")
    raise DataError(f"No macro provider could supply {series}. " + " ".join(notes), "network")


def releases(start: date, end: date, cache: DiskCache, names: list[str] | None = None) -> tuple[list[dict], str]:
    """Release dates from the first configured provider with a calendar."""
    for name in names if names is not None else provider_order():
        adapter = ADAPTERS[name]
        if hasattr(adapter, "releases") and adapter.configured():
            return adapter.releases(start, end, cache), name
    keys = [env for adapter in ADAPTERS.values() if hasattr(adapter, "releases") for env in adapter.ENV]
    raise DataError(f"needs {' or '.join(keys)}.", "not_configured")
