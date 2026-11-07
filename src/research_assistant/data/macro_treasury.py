"""U.S. Treasury daily rates (tier 0: no key): bill rates and the par yield curve, one CSV per year.
https://home.treasury.gov/resource-center/data-chart-center/interest-rates/TextView?type=daily_treasury_bill_rates
Market rates are not revised, so a day's rate is point-in-time once it is published (after the close).
"""
import csv
import io
import tempfile
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import httpx

from .. import config
from . import http
from .cache import DiskCache
from .errors import DataError

NAME, TIER, ENV, LABEL = "treasury", 0, (), "U.S. Treasury daily rates"
NOTE = "Rates only (3-month bill, 2- and 10-year yields). Inflation, unemployment and release dates need FRED."
URL = "https://home.treasury.gov/resource-center/data-chart-center/interest-rates/daily-treasury-rates.csv/{year}/all"
PAGE = "https://home.treasury.gov/resource-center/data-chart-center/interest-rates/TextView?type={kind}"
# Series name -> (CSV type, column, what it is).
SERIES = {
    "tbill_3m": ("daily_treasury_bill_rates", "13 WEEKS BANK DISCOUNT", "13-week bill, bank discount basis"),
    "treasury_2y": ("daily_treasury_yield_curve", "2 Yr", "2-year par yield (constant maturity)"),
    "treasury_10y": ("daily_treasury_yield_curve", "10 Yr", "10-year par yield (constant maturity)"),
}
transport: httpx.BaseTransport | None = None  # tests replace this; production uses the network


def configured() -> bool:
    return True


def _year(kind: str, year: int, cache: DiskCache, current_year: int) -> list[dict]:
    key = f"treasury|{kind}|{year}"
    max_age = None if year < current_year else timedelta(hours=config.MACRO_CACHE_MAX_AGE_HOURS)
    cached = cache.get(key, max_age)
    if cached is not None:
        body = cached[0]
    else:
        params = {"type": kind, "field_tdr_date_value": year, "page": "", "_format": "csv"}
        body = http.get(URL.format(year=year), params, "Treasury", transport=transport).content
        cache.put(key, body, datetime.now(timezone.utc))
    try:
        rows = list(csv.DictReader(io.StringIO(body.decode("utf-8-sig"))))
    except (UnicodeDecodeError, csv.Error) as exc:
        raise DataError(f"Treasury's {year} {kind} file is not a CSV: {exc}", "bad_data") from exc
    if rows and "Date" not in rows[0]:
        raise DataError(f"Treasury's {year} {kind} file has no Date column.", "bad_data")
    return rows


def fetch(series: str, start: date, end: date, as_of: date, cache: DiskCache) -> list[dict]:
    """Daily observations in date order: {"date", "value"} with the value in percent as published. Past years'
    files never expire; this year's refreshes. `as_of` is unused: Treasury doesn't revise, so there are no vintages."""
    kind, column, _ = SERIES[series]
    found = {}
    for year in range(start.year, end.year + 1):
        for row in _year(kind, year, cache, date.today().year):
            try:
                day = datetime.strptime(row["Date"], "%m/%d/%Y").date()
            except (KeyError, ValueError):
                continue
            value = (row.get(column) or "").strip()
            if start <= day <= end and value and value.upper() != "N/A":
                found[day] = value
    if not found:
        raise DataError(f"Treasury has no {series} between {start} and {end}.", "not_found")
    return [{"date": day.isoformat(), "value": found[day]} for day in sorted(found)]


def url(series: str) -> str:
    return PAGE.format(kind=SERIES[series][0])


def check() -> str:
    year = date.today().year
    with tempfile.TemporaryDirectory() as folder:  # a throwaway cache, so the check really reaches Treasury
        rows = _year("daily_treasury_bill_rates", year, DiskCache(Path(folder)), year)
    return f"Treasury answered with {len(rows)} days of {year} bill rates."
