"""Host-owned event records.

Providers can populate ``ToolContext.records`` with these records without giving the
model authority to create or alter them.  The adapter is intentionally small so
provider-specific calendars can be added without changing the report contract.
"""
from datetime import date, datetime

from ..contracts import EventRecord


def upcoming(
    records: dict[str, dict], ticker: str, as_of: date, observed_before: datetime | None = None
) -> list[EventRecord]:
    result = []
    for data in records.values():
        if data.get("kind") != "event" or data.get("ticker") != ticker:
            continue
        event = EventRecord.model_validate({key: value for key, value in data.items() if key != "kind"})
        if event.event_date >= as_of and (observed_before is None or event.observed_at <= observed_before):
            result.append(event)
    return sorted(result, key=lambda event: (event.event_date, event.id))
