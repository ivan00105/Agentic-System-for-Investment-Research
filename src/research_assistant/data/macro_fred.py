"""FRED (tier 1: free key): rates, inflation and unemployment as published on a day (ALFRED vintages), and the
release calendar. https://fred.stlouisfed.org/docs/api/fred/
A vintage holds the numbers known on that day, so a past cutoff never sees later revisions (REFERENCE §5).
"""
import json
import os
import tempfile
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import httpx

from .. import config
from . import http
from .cache import DiskCache
from .errors import DataError
from .sec import RateLimiter

NAME, TIER, ENV, LABEL = "fred", 1, ("FRED_API_KEY",), "FRED (St. Louis Fed)"
NOTE = "Every series as published on the cutoff day (ALFRED vintages), and the release calendar."
API = "https://api.stlouisfed.org/fred/"
# Series name -> (FRED series ID, units transformation, what it is). pc1 = percent change from a year earlier.
SERIES = {
    "tbill_3m": ("DTB3", "lin", "3-month bill, secondary market, discount basis"),
    "treasury_2y": ("DGS2", "lin", "2-year constant-maturity Treasury yield"),
    "treasury_10y": ("DGS10", "lin", "10-year constant-maturity Treasury yield"),
    "fed_funds": ("DFF", "lin", "effective federal funds rate"),
    "cpi_inflation": ("CPIAUCSL", "pc1", "CPI for all urban consumers, change from a year earlier"),
    "unemployment": ("UNRATE", "lin", "unemployment rate, seasonally adjusted"),
}
LIMITER = RateLimiter(config.FRED_MAX_REQUESTS_PER_MINUTE / 60)
transport: httpx.BaseTransport | None = None  # tests replace this; production uses the network


def configured() -> bool:
    return bool(os.getenv("FRED_API_KEY", "").strip())


def _get(path: str, params: dict, cache: DiskCache, max_age: timedelta | None) -> dict:
    key = f"fred|{path}|{json.dumps(params, sort_keys=True)}"  # never holds the API key
    cached = cache.get(key, max_age)
    if cached is not None:
        return json.loads(cached[0])
    secret = os.getenv("FRED_API_KEY", "").strip()
    LIMITER.wait()
    body = http.get(API + path, {**params, "api_key": secret, "file_type": "json"}, "FRED", transport=transport,
                    secret=secret).content
    try:
        payload = json.loads(body)
    except ValueError as exc:
        raise DataError("FRED returned something other than JSON.", "bad_data") from exc
    cache.put(key, body, datetime.now(timezone.utc))
    return payload


def _max_age(as_of: date) -> timedelta | None:
    # A vintage from before yesterday is complete and never changes; a newer one can still gain today's releases.
    return None if as_of < date.today() - timedelta(days=1) else timedelta(hours=config.MACRO_CACHE_MAX_AGE_HOURS)


def fetch(series: str, start: date, end: date, as_of: date, cache: DiskCache) -> list[dict]:
    """Observations in date order, {"date", "value"} in percent, as published on `as_of` (its ALFRED vintage)."""
    series_id, units, _ = SERIES[series]
    params = {"series_id": series_id, "units": units, "observation_start": start.isoformat(),
              "observation_end": end.isoformat(), "realtime_start": as_of.isoformat(), "realtime_end": as_of.isoformat()}
    payload = _get("series/observations", params, cache, _max_age(as_of))
    rows = [{"date": o["date"], "value": o["value"]} for o in payload.get("observations", [])
            if o.get("value") not in (None, "", ".")]  # "." is a day with no value (a holiday)
    if not rows:
        raise DataError(f"FRED has no {series_id} between {start} and {end} as published on {as_of}.", "not_found")
    return sorted(rows, key=lambda r: r["date"])


def releases(start: date, end: date, cache: DiskCache) -> list[dict]:
    """Scheduled and past release dates of config.MACRO_RELEASES between start and end, in date order."""
    found, offset = [], 0
    while True:  # pages of 1,000 until FRED's count is reached
        params = {"realtime_start": start.isoformat(), "realtime_end": end.isoformat(), "order_by": "release_date",
                  "sort_order": "asc", "include_release_dates_with_no_data": "true", "limit": 1000, "offset": offset}
        payload = _get("releases/dates", params, cache, timedelta(hours=config.MACRO_CACHE_MAX_AGE_HOURS))
        page = payload.get("release_dates", [])
        found += page
        offset += len(page)
        if not page or offset >= int(payload.get("count", 0)):
            break
    wanted = set(config.MACRO_RELEASES)
    return [{"date": r["date"], "name": r.get("release_name"), "release_id": r["release_id"],
             "url": f"https://fred.stlouisfed.org/release?rid={r['release_id']}"}
            for r in found if r.get("release_id") in wanted and start.isoformat() <= r.get("date", "") <= end.isoformat()]


def url(series: str) -> str:
    return f"https://fred.stlouisfed.org/series/{SERIES[series][0]}"


def check() -> str:
    with tempfile.TemporaryDirectory() as folder:  # a throwaway cache, so the check really reaches FRED
        _get("series", {"series_id": "DTB3"}, DiskCache(Path(folder)), None)
    return "FRED accepted the API key."
