"""Mocked exchange-rate providers that answer with made-up weekday rates (never live data)."""
from datetime import date, timedelta
from urllib.parse import parse_qs

import httpx


def weekdays(start: date, end: date) -> list[date]:
    return [start + timedelta(days=i) for i in range((end - start).days + 1) if (start + timedelta(days=i)).weekday() < 5]


def cny(day: date) -> float:
    """7.0 CNY per dollar in BABA's fiscal 2025 (to 31 March 2025), 7.2 after."""
    return 7.0 if day < date(2025, 4, 1) else 7.2


class Frankfurter:
    """GET /v1/{start}..{end}?base=USD&symbols=X. Like the real one, the answer starts on the last rate before start."""

    def __init__(self, rates: dict | None = None):
        self.rates, self.requests = rates if rates is not None else {"CNY": cny}, []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        start, end = map(date.fromisoformat, request.url.path.rsplit("/", 1)[-1].split(".."))
        code = request.url.params["symbols"]
        if code not in self.rates:
            return httpx.Response(404, json={"message": "not found"})
        days = [d for d in weekdays(start - timedelta(days=4), end) if self.rates[code](d) is not None]
        return httpx.Response(200, json={"amount": 1.0, "base": "USD", "rates": {
            d.isoformat(): {code: self.rates[code](d)} for d in days}})


class Fred:
    """series/observations for H.10 series; `rates` maps a series ID to a function of the day."""

    def __init__(self, rates: dict):
        self.rates, self.requests = rates, []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        params = {k: v[0] for k, v in parse_qs(request.url.query.decode()).items()}
        start, end = date.fromisoformat(params["observation_start"]), date.fromisoformat(params["observation_end"])
        values = self.rates[params["series_id"]]
        return httpx.Response(200, json={"observations": [
            {"date": d.isoformat(), "value": str(values(d))} for d in weekdays(start, end)]})
