from datetime import date, datetime, timezone
from decimal import Decimal

import pytest

from research_assistant.contracts import EventRecord, OutlookOutcome
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
