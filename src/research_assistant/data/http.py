"""One retrying GET for the keyed and keyless HTTP providers (Treasury, FRED, ...). SEC has its own client."""
import time

import httpx

from .. import config
from .errors import DataError

RETRY_STATUSES = {429, 500, 502, 503, 504}


def get(url: str, params: dict, label: str, *, headers: dict | None = None, transport: httpx.BaseTransport | None = None,
        secret: str = "", sleep=time.sleep) -> httpx.Response:
    """A 200 response, after retrying 429, 5xx and network errors; any other answer is a DataError naming `label`.
    `secret` (a key sent in the URL) is blanked out of any error message."""
    attempts = config.HTTP_RETRIES + 1
    with httpx.Client(transport=transport, timeout=config.HTTP_TIMEOUT_SECONDS) as client:
        for attempt in range(attempts):
            if attempt:
                sleep(config.HTTP_RETRY_BACKOFF_SECONDS * 2 ** (attempt - 1))
            try:
                response = client.get(url, params=params, headers=headers)
            except httpx.TransportError as exc:
                if attempt == attempts - 1:
                    message = str(exc).replace(secret, "***") if secret else str(exc)
                    raise DataError(f"{label} did not respond: {message}", "network") from exc
                continue
            if response.status_code in RETRY_STATUSES and attempt < attempts - 1:
                continue
            if response.status_code == 404:
                raise DataError(f"{label} has no such data.", "not_found", 404)
            if response.status_code != 200:
                raise DataError(f"{label} returned HTTP {response.status_code}.", "http_error", response.status_code)
            return response
    raise AssertionError("unreachable")
