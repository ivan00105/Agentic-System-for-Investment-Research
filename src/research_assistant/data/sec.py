"""One SEC EDGAR client for every tool: fair-access pacing, retries and a disk cache.

SEC asks for a User-Agent with a contact email and at most 10 requests per second
(https://www.sec.gov/about/developer-resources). All clients in this process share one limiter,
so tools running in parallel stay under the limit together. Responses are cached on disk by URL.
Archived filings never change, so they never expire. The JSON APIs expire after
config.SEC_CACHE_MAX_AGE_HOURS.
"""
import json
import os
import re
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlsplit

import httpx

from .. import config
from .cache import DiskCache
from .errors import DataError

SEC_HOSTS = {"data.sec.gov", "www.sec.gov"}
# Everything under an accession folder is an immutable filing.
ARCHIVE_PREFIX = "/Archives/edgar/data/"
RETRY_STATUSES = {429, 500, 502, 503, 504}


class SecError(DataError):
    """SEC gave no usable answer."""


@dataclass(frozen=True)
class SecResponse:
    url: str
    body: bytes
    retrieved_at: datetime  # when SEC sent these bytes, also for cache hits
    from_cache: bool

    def json(self):
        return json.loads(self.body)


class RateLimiter:
    """Spaces calls at least 1/per_second apart, across threads."""

    def __init__(self, per_second: float, clock=time.monotonic, sleep=time.sleep):
        self._interval = 1 / per_second
        self._clock, self._sleep = clock, sleep
        self._next = float("-inf")
        self._lock = threading.Lock()

    def wait(self):
        # Reserve the next free slot under the lock, then sleep outside it.
        with self._lock:
            now = self._clock()
            slot = max(now, self._next)
            self._next = slot + self._interval
        if slot > now:
            self._sleep(slot - now)


LIMITER = RateLimiter(config.SEC_MAX_REQUESTS_PER_SECOND)


def cik10(cik: int | str) -> str:
    """The zero-padded 10-digit CIK that SEC API paths use."""
    text = str(cik).strip()
    if not re.fullmatch(r"[0-9]{1,10}", text):
        raise ValueError(f"Not a CIK: {cik!r}")
    return text.zfill(10)


class SecClient:
    def __init__(self, user_agent: str | None = None, cache_dir: Path | None = None, *,
                 transport: httpx.BaseTransport | None = None, limiter: RateLimiter | None = None, sleep=time.sleep):
        agent = (os.getenv("SEC_USER_AGENT", "") if user_agent is None else user_agent).strip()
        self.user_agent = agent if "@" in agent else None
        self.cache = DiskCache(Path(cache_dir) if cache_dir else config.data_dir() / "sec_cache")
        self._limiter = limiter or LIMITER
        self._sleep = sleep
        self._http = httpx.Client(transport=transport, timeout=config.SEC_TIMEOUT_SECONDS, follow_redirects=False)

    @property
    def configured(self) -> bool:
        return self.user_agent is not None

    def companyfacts(self, cik: int | str) -> SecResponse:
        return self.get(f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik10(cik)}.json")

    def submissions(self, cik: int | str) -> SecResponse:
        return self.get(f"https://data.sec.gov/submissions/CIK{cik10(cik)}.json")

    def get(self, url: str) -> SecResponse:
        parts = urlsplit(url)
        if parts.scheme != "https" or parts.hostname not in SEC_HOSTS:
            raise ValueError(f"Not an SEC URL: {url}")
        immutable = parts.path.startswith(ARCHIVE_PREFIX)
        cached = self.cache.get(url, None if immutable else timedelta(hours=config.SEC_CACHE_MAX_AGE_HOURS))
        if cached is not None:
            return SecResponse(url, cached[0], cached[1], from_cache=True)
        if not self.configured:
            raise SecError("SEC access is not configured: set SEC_USER_AGENT to a name and contact email.",
                           "not_configured")
        response = SecResponse(url, self._fetch(url), datetime.now(timezone.utc), from_cache=False)
        self.cache.put(url, response.body, response.retrieved_at)
        return response

    def close(self):
        self._http.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def _fetch(self, url: str) -> bytes:
        attempts = config.SEC_RETRIES + 1
        for attempt in range(attempts):
            if attempt:
                self._sleep(config.SEC_RETRY_BACKOFF_SECONDS * 2 ** (attempt - 1))
            last = attempt == attempts - 1
            self._limiter.wait()
            try:
                with self._http.stream("GET", url, headers={"User-Agent": self.user_agent}) as response:
                    if response.status_code in RETRY_STATUSES and not last:
                        continue
                    if response.status_code != 200:
                        raise _status_error(url, response.status_code)
                    return _read_body(url, response)
            except httpx.TransportError as exc:
                if last:
                    raise SecError(f"SEC did not respond for {url} after {attempts} tries: {exc}", "network") from exc
        raise AssertionError("unreachable")


def _read_body(url: str, response: httpx.Response) -> bytes:
    limit = config.SEC_MAX_RESPONSE_BYTES
    chunks, size = [], 0
    for chunk in response.iter_bytes():
        size += len(chunk)
        if size > limit:
            raise SecError(f"SEC response for {url} is larger than SEC_MAX_RESPONSE_BYTES "
                           f"({limit:,} bytes) in config.py.", "too_large")
        chunks.append(chunk)
    return b"".join(chunks)


def _status_error(url: str, status: int) -> SecError:
    if status == 404:
        return SecError(f"SEC has no document at {url}.", "not_found", status)
    hint = " SEC refuses requests without a contact email in SEC_USER_AGENT, or above 10 per second." if status == 403 else ""
    return SecError(f"SEC returned HTTP {status} for {url}.{hint}", "http_error", status)
