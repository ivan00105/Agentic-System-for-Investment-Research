from datetime import datetime, timezone

import pandas as pd

from research_assistant.agents.evidence import SavedRun, _recompute_outlook
from sec_files import make_context
from research_assistant.data import prices_yfinance
from research_assistant.tools.get_outlook import GetOutlookInput, run


def test_get_outlook_returns_citable_horizon_records(tmp_path, monkeypatch):
    dates = pd.date_range("2025-11-03", periods=200, freq="D")

    def history(ticker, start, end):
        offset = 0.2 if ticker == "AAPL" else 0.1
        close = [100 + index * offset for index in range(len(dates))]
        frame = pd.DataFrame(
            {"Close": close, "Adj Close": close, "Volume": [1.0] * len(dates),
             "Dividends": [0.0] * len(dates), "Stock Splits": [0.0] * len(dates)},
            index=dates,
        )
        return frame, pd.Series(dtype=float)

    monkeypatch.setattr(prices_yfinance, "_history", history)
    context = make_context(tmp_path, cutoff=datetime(2026, 4, 20, tzinfo=timezone.utc))
    context.price_providers = ["yfinance"]

    result = run(GetOutlookInput(ticker="AAPL", start=dates[0].date(), horizons=[5, 20]), context)

    assert result.status == "ok"
    assert len(result.ids) >= 12
    assert all(context.records[record_id]["kind"] == "calc" for record_id in result.ids)
    assert {context.records[record_id]["inputs"]["horizon"] for record_id in result.ids} == {5, 20}
    for horizon in ("5", "20"):
        metrics = result.data["horizons"][horizon]["metrics"]
        assert metrics["own_return_low"]["id"] in result.ids
        assert metrics["own_return_low"]["value"] == context.records[metrics["own_return_low"]["id"]]["value"]
        assert "unavailable_metrics" in result.data["horizons"][horizon]
    saved = SavedRun([], context.records, {}, None, None)
    mismatches = [(record_id, context.records[record_id]["value"],
                   _recompute_outlook(context.records[record_id], saved).model_dump())
                  for record_id in result.ids
                  if _recompute_outlook(context.records[record_id], saved).data["value"] != context.records[record_id]["value"]]
    assert not mismatches, mismatches[0]


def test_get_outlook_rejects_non_positive_horizons(tmp_path):
    context = make_context(tmp_path, cutoff=datetime(2026, 4, 20, tzinfo=timezone.utc))

    result = run(GetOutlookInput(ticker="AAPL", horizons=[0]), context)

    assert result.status == "invalid"
