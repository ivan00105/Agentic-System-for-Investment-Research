from datetime import date, datetime, timezone

import pandas as pd
import pytest
from sec_files import make_context

from research_assistant.data import prices_yfinance
from research_assistant.tools.get_prices import GetPricesInput, run

CUTOFF = datetime(2026, 3, 5, 0, tzinfo=timezone.utc)  # 4 March, 19:00 in New York


@pytest.fixture(autouse=True)
def yahoo(monkeypatch):
    days = pd.to_datetime(["2026-03-02", "2026-03-03", "2026-03-04", "2026-03-05"])
    frame = pd.DataFrame({"Close": [10.0, 11.0, 12.0, 13.0], "Adj Close": [9.0, 10.0, 11.0, 12.0],
                          "Volume": [1.0] * 4, "Dividends": [0.0] * 4, "Stock Splits": [0.0] * 4}, index=days)
    monkeypatch.setattr(prices_yfinance, "_history", lambda ticker, start, end: (frame, pd.Series(dtype=float)))


def get(tmp_path, **args):
    context = make_context(tmp_path, cutoff=CUTOFF)
    context.cache_dir = tmp_path
    return run(GetPricesInput(**args), context), context


def test_series_is_stored_under_one_id_for_calculate(tmp_path):
    result, context = get(tmp_path, ticker="aapl", start=date(2026, 3, 1))
    assert result.status == "ok" and result.data["trading_days"] == 3
    record = context.records[result.ids[0]]
    assert record["kind"] == "prices" and record["source"] == "yfinance" and len(record["rows"]) == 3
    assert result.data["last"] == {"date": "2026-03-04", "close": 12.0, "adj_close": 11.0}


def test_falling_back_from_the_preferred_provider_is_labelled(tmp_path):
    result, _ = get(tmp_path, ticker="AAPL", start=date(2026, 3, 1))
    assert result.source == "yfinance (fallback)"
    assert "tiingo skipped: not configured (set TIINGO_API_KEY)." in result.warnings


def test_pinned_provider_is_not_a_fallback(tmp_path):
    context = make_context(tmp_path, cutoff=CUTOFF)
    context.cache_dir, context.price_providers = tmp_path, ["yfinance"]
    assert run(GetPricesInput(ticker="AAPL", start=date(2026, 3, 1)), context).source == "yfinance"


def test_end_after_the_cutoff_is_moved_back(tmp_path):
    result, _ = get(tmp_path, ticker="AAPL", start=date(2026, 3, 1), end=date(2026, 3, 9))
    assert result.data["end"] == "2026-03-04"
    assert any("not public at the cutoff" in w for w in result.warnings)


def test_start_after_end_is_invalid(tmp_path):
    result, _ = get(tmp_path, ticker="AAPL", start=date(2026, 3, 4), end=date(2026, 3, 2))
    assert result.status == "invalid"
