from datetime import date
from decimal import Decimal

import httpx
import pytest
from fx_rates import Frankfurter, Fred, weekdays

from research_assistant.data import fx, fx_frankfurter, macro_fred
from research_assistant.data.cache import DiskCache
from research_assistant.data.errors import DataError


@pytest.fixture
def cache(tmp_path):
    return DiskCache(tmp_path / "fx")


def frankfurter(monkeypatch, rates=None) -> Frankfurter:
    mock = Frankfurter(rates)
    monkeypatch.setattr(fx_frankfurter, "transport", httpx.MockTransport(mock))
    return mock


def test_a_years_average_from_frankfurter_is_labelled_a_fallback_without_a_fred_key(monkeypatch, cache):
    frankfurter(monkeypatch)
    rate = fx.average("CNY", date(2025, 4, 1), date(2026, 3, 31), cache)
    assert rate.per_usd == Decimal("7.200000") and rate.basis == "average"
    # The day before the year that Frankfurter also sends is left out.
    assert (rate.first, rate.last, rate.days) == (date(2025, 4, 1), date(2026, 3, 31), len(weekdays(date(2025, 4, 1), date(2026, 3, 31))))
    assert rate.source == "Frankfurter (ECB reference rates) (fallback)" and rate.series is None
    assert rate.notes == ("FRED H.10 (Federal Reserve) skipped: not configured (set FRED_API_KEY).",)


def test_fred_goes_first_when_keyed_and_dollar_quotes_are_inverted(monkeypatch, cache):
    monkeypatch.setenv("FRED_API_KEY", "test-key")
    mock = Fred({"DEXUSEU": lambda day: 1.25})  # US dollars per euro
    monkeypatch.setattr(macro_fred, "transport", httpx.MockTransport(mock))
    monkeypatch.setattr(macro_fred.LIMITER, "wait", lambda: None)
    ecb = frankfurter(monkeypatch, {"EUR": lambda day: 0.9})
    rate = fx.average("EUR", date(2025, 1, 1), date(2025, 12, 31), cache)
    assert rate.per_usd == Decimal("0.800000") and rate.source == "FRED H.10 (Federal Reserve)"
    assert rate.series == "DEXUSEU" and rate.url.endswith("/DEXUSEU") and ecb.requests == []


def test_twd_needs_fred(monkeypatch, cache):
    ecb = frankfurter(monkeypatch)
    with pytest.raises(DataError, match="FRED_API_KEY"):
        fx.at("TWD", date(2025, 12, 31), cache)
    assert ecb.requests == []


def test_a_year_end_rate_is_the_last_rate_on_or_before_the_day(monkeypatch, cache):
    frankfurter(monkeypatch, {"CNY": lambda day: 7 + day.day / 1000})
    rate = fx.at("CNY", date(2026, 3, 28), cache)  # a Saturday: Friday's rate
    assert rate.per_usd == Decimal("7.027000") and rate.basis == "year_end"
    assert (rate.first, rate.last, rate.days) == (date(2026, 3, 27), date(2026, 3, 27), 1)


def test_rates_that_dont_cover_the_year_are_not_averaged(monkeypatch, cache):
    frankfurter(monkeypatch, {"CNY": lambda day: 7.1 if day >= date(2025, 10, 1) else None})
    with pytest.raises(DataError, match="only from 2025-10-01"):
        fx.average("CNY", date(2025, 4, 1), date(2026, 3, 31), cache)


def test_a_finished_years_rates_are_cached_for_good(monkeypatch, cache):
    ecb = frankfurter(monkeypatch)
    first = fx.average("CNY", date(2024, 4, 1), date(2025, 3, 31), cache)
    assert fx.average("CNY", date(2024, 4, 1), date(2025, 3, 31), cache) == first and len(ecb.requests) == 1
