"""FRED H.10 exchange rates (tier 1: free key): the Federal Reserve's daily noon buying rates in New York.
https://fred.stlouisfed.org/categories/94 . A published day's rate is final, so it is never revised.
"""
from datetime import date, timedelta
from decimal import Decimal

from .. import config
from . import macro_fred
from .cache import DiskCache
from .errors import DataError

NAME, TIER, ENV, LABEL = "fred", 1, ("FRED_API_KEY",), "FRED H.10 (Federal Reserve)"
NOTE = "Daily noon buying rates in New York for 22 currencies, including TWD."
# Currency -> (FRED series, True when quoted as US dollars per unit of the currency rather than units per dollar).
SERIES = {
    "AUD": ("DEXUSAL", True), "BRL": ("DEXBZUS", False), "CAD": ("DEXCAUS", False), "CHF": ("DEXSZUS", False),
    "CNY": ("DEXCHUS", False), "DKK": ("DEXDNUS", False), "EUR": ("DEXUSEU", True), "GBP": ("DEXUSUK", True),
    "HKD": ("DEXHKUS", False), "INR": ("DEXINUS", False), "JPY": ("DEXJPUS", False), "KRW": ("DEXKOUS", False),
    "LKR": ("DEXSLUS", False), "MXN": ("DEXMXUS", False), "MYR": ("DEXMAUS", False), "NOK": ("DEXNOUS", False),
    "NZD": ("DEXUSNZ", True), "SEK": ("DEXSDUS", False), "SGD": ("DEXSIUS", False), "THB": ("DEXTHUS", False),
    "TWD": ("DEXTAUS", False), "ZAR": ("DEXSFUS", False),
}


def configured() -> bool:
    return macro_fred.configured()


def fetch(currency: str, start: date, end: date, cache: DiskCache) -> list[dict]:
    """Daily rates in date order, {"date", "value"}, as units of the currency per US dollar."""
    series, inverted = SERIES[currency]
    final = end < date.today() - timedelta(days=config.FX_FINAL_AFTER_DAYS)
    params = {"series_id": series, "observation_start": start.isoformat(), "observation_end": end.isoformat()}
    payload = macro_fred._get("series/observations", params, cache,
                              None if final else timedelta(hours=config.FX_CACHE_MAX_AGE_HOURS))
    rows = [{"date": o["date"], "value": str(1 / Decimal(o["value"])) if inverted else o["value"]}
            for o in payload.get("observations", []) if o.get("value") not in (None, "", ".")]  # ".": a holiday
    if not rows:
        raise DataError(f"FRED has no {series} rates between {start} and {end}.", "not_found")
    return sorted(rows, key=lambda r: r["date"])


def url(currency: str) -> str:
    return f"https://fred.stlouisfed.org/series/{SERIES[currency][0]}"


def series(currency: str) -> str:
    return SERIES[currency][0]


def check() -> str:
    return macro_fred.check()
