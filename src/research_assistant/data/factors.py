"""Ken French factor CSV provider, disk-cached like the other data sources."""
import io
import zipfile
from datetime import datetime, timedelta, timezone

import httpx

from .. import config
from .cache import DiskCache
from .http import get

FIVE_FACTORS_URL = "https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/ftp/F-F_Research_Data_5_Factors_2x3_daily_CSV.zip"
MOMENTUM_URL = "https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/ftp/F-F_Momentum_Factor_daily_CSV.zip"


def _daily_zip(url: str, cache: DiskCache, name: str, transport: httpx.BaseTransport | None = None) -> list[list[str]]:
    key = f"ken_french:{name}"
    cached = cache.get(key, timedelta(days=config.FACTOR_CACHE_MAX_AGE_DAYS))
    if cached:
        body = cached[0]
    else:
        response = get(url, {}, "Ken French factor library", transport=transport)
        body = response.content
        cache.put(key, body, datetime.now(timezone.utc))
    with zipfile.ZipFile(io.BytesIO(body)) as archive:
        csv_name = next(name for name in archive.namelist() if name.lower().endswith(".csv"))
        text = archive.read(csv_name).decode("latin1")
    lines = text.splitlines()
    start = next((index for index, line in enumerate(lines)
                  if len(line.split(",")[0].strip()) == 8 and line.split(",")[0].strip().isdigit()), None)
    if start is None:
        raise ValueError("Ken French CSV has no daily rows.")
    return [line.split(",") for line in lines[start:] if len(line.split(",")) >= 2]


def five_factors(cache: DiskCache, transport: httpx.BaseTransport | None = None) -> dict[str, dict[str, float]]:
    rows = _daily_zip(FIVE_FACTORS_URL, cache, "five_factors", transport)
    factors: dict[str, dict[str, float]] = {}
    for row in rows:
        date = row[0].strip()
        if len(date) != 8 or not date.isdigit():
            break
        try:
            values = [float(value.strip()) / 100 for value in row[1:6]]
        except ValueError:
            break
        factors[date] = dict(zip(("MKT-RF", "SMB", "HML", "RMW", "CMA"), values, strict=True))
        try:
            factors[date]["RF"] = float(row[6].strip()) / 100
        except (ValueError, IndexError):
            factors[date]["RF"] = 0.0
    return factors


def momentum(cache: DiskCache, transport: httpx.BaseTransport | None = None) -> dict[str, float]:
    rows = _daily_zip(MOMENTUM_URL, cache, "momentum", transport)
    result = {}
    for row in rows:
        date = row[0].strip()
        if len(date) != 8 or not date.isdigit():
            break
        try:
            result[date] = float(row[1].strip()) / 100
        except ValueError:
            break
    return result
