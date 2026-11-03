from datetime import date, datetime
from zoneinfo import ZoneInfo

import httpx
import pandas as pd
import pytest

from research_assistant.data import prices, prices_tiingo, prices_yfinance
from research_assistant.data.cache import DiskCache
from research_assistant.data.errors import DataError

DAYS = pd.to_datetime(["2026-03-02", "2026-03-03", "2026-03-04"])


def yahoo(closes=(50.0, 51.0, 51.0), splits=None):
    """A frame shaped like yfinance's history(auto_adjust=False): Close already split-adjusted."""
    frame = pd.DataFrame({"Open": closes, "High": closes, "Low": closes, "Close": closes, "Adj Close": [c * 0.99 for c in closes],
                          "Volume": [1e6] * 3, "Dividends": [0.0, 0.25, 0.0], "Stock Splits": [0.0, 0.0, 2.0]}, index=DAYS)
    return frame, pd.Series(splits if splits is not None else {DAYS[2]: 2.0})


@pytest.fixture
def calls(monkeypatch):
    seen = []

    def history(ticker, start, end):
        seen.append(ticker)
        return yahoo()
    monkeypatch.setattr(prices_yfinance, "_history", history)
    return seen


def tiingo(monkeypatch, handler):
    monkeypatch.setenv("TIINGO_API_KEY", "test-key")
    monkeypatch.setattr(prices_tiingo, "transport", httpx.MockTransport(handler))


def test_yfinance_rebuilds_the_as_traded_close_from_splits():
    rows = prices_yfinance.to_rows(*yahoo())
    assert [r["close"] for r in rows] == [100.0, 102.0, 51.0]  # 2:1 split on the third day
    assert rows[1]["dividend"] == 0.25 and rows[2]["split"] == 2.0 and rows[0]["adj_close"] == pytest.approx(49.5)


def test_yfinance_counts_splits_after_the_requested_window():
    frame, _ = yahoo((25.0, 25.5, 25.5))
    rows = prices_yfinance.to_rows(frame, pd.Series({DAYS[2]: 2.0, pd.Timestamp("2026-06-01"): 2.0}))
    assert [r["close"] for r in rows] == [100.0, 102.0, 51.0]


def test_tiingo_sends_the_key_and_maps_fields(monkeypatch):
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(200, json=[{"date": "2026-03-02T00:00:00.000Z", "close": 100.0, "adjClose": 99.0,
                                          "volume": 5, "divCash": 0.0, "splitFactor": 1.0}])
    tiingo(monkeypatch, handler)
    rows = prices_tiingo.fetch("AAPL", date(2026, 3, 1), date(2026, 3, 2))
    assert rows == [{"date": "2026-03-02", "close": 100.0, "adj_close": 99.0, "volume": 5, "dividend": 0.0, "split": 1.0}]
    assert seen[0].headers["Authorization"] == "Token test-key" and seen[0].url.params["startDate"] == "2026-03-01"


def test_missing_key_skips_tiingo_with_a_note(tmp_path, calls):
    rows, source, notes = prices.fetch("aapl", date(2026, 3, 1), date(2026, 3, 4), DiskCache(tmp_path))
    assert source == "yfinance" and calls == ["AAPL"] and len(rows) == 3
    assert notes == ["tiingo skipped: not configured (set TIINGO_API_KEY)."]


def test_failing_provider_falls_back_and_says_so(tmp_path, calls, monkeypatch):
    tiingo(monkeypatch, lambda request: httpx.Response(500))
    monkeypatch.setattr("research_assistant.config.HTTP_RETRIES", 0)
    _, source, notes = prices.fetch("AAPL", date(2026, 3, 1), date(2026, 3, 4), DiskCache(tmp_path))
    assert source == "yfinance" and notes[0].startswith("tiingo failed: Tiingo returned HTTP 500")


def test_unknown_ticker_everywhere_is_not_found(tmp_path, monkeypatch):
    tiingo(monkeypatch, lambda request: httpx.Response(404))
    monkeypatch.setattr(prices_yfinance, "_history", lambda *a: (pd.DataFrame(), pd.Series(dtype=float)))
    with pytest.raises(DataError) as error:
        prices.fetch("NOPE", date(2026, 3, 1), date(2026, 3, 4), DiskCache(tmp_path))
    assert error.value.code == "not_found"


def test_days_without_a_close_are_left_out_and_counted(tmp_path, monkeypatch):
    frame, splits = yahoo((50.0, 51.0, float("nan")))
    monkeypatch.setattr(prices_yfinance, "_history", lambda *a: (frame, splits))
    for _ in range(2):  # fresh, then from the cache
        rows, _, notes = prices.fetch("NVDA", date(2026, 3, 1), date(2026, 3, 4), DiskCache(tmp_path))
        assert [r["date"] for r in rows] == ["2026-03-02", "2026-03-03"]
        assert notes[-1] == "1 day(s) without a close left out: 2026-03-04."


def test_cached_series_is_reused(tmp_path, calls):
    for _ in range(2):
        prices.fetch("AAPL", date(2026, 3, 1), date(2026, 3, 4), DiskCache(tmp_path))
    assert calls == ["AAPL"]


def test_provider_order_follows_the_environment(monkeypatch):
    assert prices.provider_order() == ["tiingo", "yfinance"]
    monkeypatch.setenv("PRICE_PROVIDERS", "YFinance, unknown ,tiingo")
    assert prices.provider_order() == ["yfinance", "tiingo"]


@pytest.mark.parametrize(("hour", "day"), [(17, date(2026, 3, 3)), (19, date(2026, 3, 4))])
def test_a_close_is_known_from_the_configured_new_york_hour(hour, day):
    assert prices.last_known_day(datetime(2026, 3, 4, hour, tzinfo=ZoneInfo("America/New_York"))) == day
