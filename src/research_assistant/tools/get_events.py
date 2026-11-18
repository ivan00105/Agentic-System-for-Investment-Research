"""Return timestamped earnings and dividend calendar records supplied by the host."""
from pydantic import BaseModel, Field

from ..data.events import upcoming
from .result import Tool, ToolContext, ToolResult


class GetEventsInput(BaseModel):
    ticker: str = Field(min_length=1, max_length=12)
    event_types: list[str] | None = Field(
        default=None, description="Optional event types: earnings, ex_dividend or event."
    )


def run(args: GetEventsInput, context: ToolContext) -> ToolResult:
    events = upcoming(context.records, args.ticker.upper(), context.cutoff.date(), context.cutoff)
    if args.event_types is not None:
        allowed = {"earnings", "ex_dividend", "event"}
        invalid = sorted(set(args.event_types) - allowed)
        if invalid:
            return ToolResult(status="invalid", source="events", warnings=[f"Unknown event type: {invalid[0]}."])
        events = [event for event in events if event.event_type in args.event_types]
    if not events:
        return ToolResult(
            status="unavailable",
            source="events",
            warnings=["No configured event-calendar provider returned a timestamped record."],
        )
    ids = [event.id for event in events]
    return ToolResult(
        status="ok",
        data={"ticker": args.ticker.upper(), "events": [event.model_dump(mode="json") for event in events]},
        ids=ids,
        source="host event records",
    )


TOOL = Tool(
    "get_events",
    "Read host-owned upcoming earnings, ex-dividend and other event records. "
    "Dates are observations, not forecasts, and are never invented by the model.",
    GetEventsInput,
    run,
    "events",
)
