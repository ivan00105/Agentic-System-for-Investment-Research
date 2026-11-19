from datetime import date, datetime, timezone
from decimal import Decimal

import pytest

from research_assistant.contracts import EventRecord, OutlookOutcome
from research_assistant.data import events
from research_assistant.tools import get_events as get_events_module
from research_assistant.store import Store
from research_assistant.tools.get_events import GetEventsInput, run as get_events
from sec_files import make_context


def _event():
    observed = datetime(2026, 10, 31, 12, tzinfo=timezone.utc)
    return EventRecord(
        id="event-aapl-earnings",
        ticker="AAPL",
        event_type="earnings",
        event_date=date(2026, 11, 5),
        announced_at=observed,
        observed_at=observed,
        source="mock-calendar",
    )


def test_events_are_host_owned_and_cutoff_filtered(tmp_path):
    context = make_context(tmp_path)
    context.remember({"kind": "event", **_event().model_dump(mode="json")})
    result = get_events(GetEventsInput(ticker="AAPL"), context)
    assert result.status == "ok"
    assert result.ids == ["event-aapl-earnings"]

    context.remember({"kind": "event", **_event().model_copy(
        update={"id": "event-aapl-old", "event_date": date(2026, 10, 1)}
    ).model_dump(mode="json")})
    assert get_events(GetEventsInput(ticker="AAPL"), context).ids == ["event-aapl-earnings"]


def test_events_fetch_at_cutoff_and_store_option_market_view(tmp_path, monkeypatch):
    context = make_context(tmp_path)
    monkeypatch.setattr(events, "fetch", lambda *args, **kwargs: (
        [{"kind": "earnings", "date": "2026-11-05", "source": "finnhub",
          "status": "upcoming", "details": {}}],
        "finnhub", [],
    ))
    monkeypatch.setattr(get_events_module, "_add_typical_results_move",
                        lambda *args, **kwargs: None)
    monkeypatch.setattr(get_events_module, "_add_option_implied_range",
                        lambda *args, **kwargs: None)

    result = get_events(GetEventsInput(ticker="AAPL"), context)
    assert result.status == "ok"
    record = context.records[result.ids[0]]
    assert record["event_date"] == "2026-11-05"
    assert record["announced_at"] == "2026-11-01T00:00:00+00:00"
    assert record["observed_at"] == "2026-11-01T00:00:00+00:00"


def test_live_option_range_is_at_the_money_straddle(tmp_path, monkeypatch):
    context = make_context(tmp_path)
    adapter = events.ADAPTERS["yfinance"]
    monkeypatch.setattr(adapter, "option_expiries", lambda ticker: ["2026-11-06", "2026-12-18"])
    monkeypatch.setattr(adapter, "_option_snapshot", lambda ticker, expiry: {
        "spot": 100.0,
        "calls": [{"strike": 100.0, "bid": 8.0, "ask": 10.0, "lastPrice": 9.0}],
        "puts": [{"strike": 100.0, "bid": 7.0, "ask": 9.0, "lastPrice": 8.0}],
    })
    warnings = []
    get_events_module._add_option_implied_range("AAPL", [date(2026, 11, 5)], context, warnings)
    record = next(record for record in context.records.values()
                  if record.get("formula") == "option_implied_range")
    assert record["value"] == 0.17
    assert record["inputs"]["spot"] == 100.0


def test_outlook_log_is_hash_chained_and_outcomes_are_appended(tmp_path):
    store = Store(tmp_path)
    record = {"id": "risk-aapl-20", "ticker": "AAPL", "issued_at": "2026-11-01T12:00:00Z", "value": 0.2}
    first = store.append_outlook_record(record)
    assert first.previous_hash is None
    assert store.append_outlook_record(record).sequence == first.sequence
    with pytest.raises(Exception, match="immutable"):
        store.append_outlook_record({**record, "value": 0.3})

    outcome = OutlookOutcome(
        forecast_id=record["id"],
        resolved_at=datetime(2026, 12, 1, tzinfo=timezone.utc),
        status="resolved",
        actual=Decimal("0.18"),
    )
    second = store.append_outlook_outcome(outcome)
    assert second.previous_hash == first.hash
    assert [entry.kind for entry in store.outlook_log()] == ["record", "outcome"]


def test_outlook_scheduler_uses_exchange_session_before_close(tmp_path, monkeypatch):
    from research_assistant import outlook_scheduler
    from research_assistant.tools.result import ToolResult

    scheduler = outlook_scheduler.OutlookScheduler(Store(tmp_path), tmp_path)

    def fake_outlook(args, context):
        record = {
            "id": f"risk-{args.ticker}-{args.horizons[0]}",
            "kind": "calc",
            "formula": "outlook_own_return_low",
            "ticker": args.ticker,
            "value": -0.1,
            "inputs": {"horizon": args.horizons[0]},
            "issued_at": "2026-11-19T20:40:00Z",
        }
        context.remember(record)
        return ToolResult(status="ok", source="test", ids=[record["id"]])

    monkeypatch.setattr(outlook_scheduler, "get_outlook", fake_outlook)
    monkeypatch.setattr(outlook_scheduler, "get_prices",
                        lambda args, context: ToolResult(status="unavailable", source="test", warnings=["mock"]))
    now = datetime(2026, 11, 19, 20, 40, tzinfo=timezone.utc)  # 15:40 in New York
    scheduler.run_once(now)

    entries = scheduler.store.outlook_log()
    assert entries
    assert all(entry.payload["anchor_date"] == "2026-11-19" for entry in entries if entry.kind == "record")
