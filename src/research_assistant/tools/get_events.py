"""Return timestamped earnings, dividend and live market-view records supplied by the host."""
import statistics
from datetime import date, timedelta

from pydantic import BaseModel, Field

from ..data import sec_filings
from ..data import events
from ..data.errors import DataError
from .get_prices import GetPricesInput, run as get_prices
from ..data.events import upcoming
from .result import Tool, ToolContext, ToolResult, make_id


class GetEventsInput(BaseModel):
    ticker: str = Field(min_length=1, max_length=12)
    event_types: list[str] | None = Field(
        default=None, description="Optional event types: earnings, ex_dividend or event."
    )


def run(args: GetEventsInput, context: ToolContext) -> ToolResult:
    ticker = args.ticker.upper()
    upcoming_events = upcoming(context.records, ticker, context.cutoff.date(), context.cutoff)
    if args.event_types is not None:
        allowed = {"earnings", "ex_dividend", "event"}
        invalid = sorted(set(args.event_types) - allowed)
        if invalid:
            return ToolResult(status="invalid", source="events", warnings=[f"Unknown event type: {invalid[0]}."])
        upcoming_events = [event for event in upcoming_events if event.event_type in args.event_types]

    # Historical/frozen/replay contexts are evidence-only: never make a live provider call.
    live_ids = []
    warnings = []
    if not context.historical and not upcoming_events:
        start = context.cutoff.date() - timedelta(days=30)
        end = context.cutoff.date() + timedelta(days=366)
        try:
            rows, source, provider_notes = events.fetch(ticker, start, end, context.cutoff,
                                                        context.cache("event_cache"))
            warnings.extend(provider_notes)
            for row in rows:
                event_date = date.fromisoformat(row["date"])
                if event_date > context.cutoff.date():
                    status = "upcoming"
                elif event_date == context.cutoff.date():
                    status = "upcoming"
                else:
                    status = "occurred"
                record = {
                    "id": make_id("event", ticker, row["kind"], row["date"], source),
                    "kind": "event",
                    "ticker": ticker,
                    "event_type": row["kind"],
                    "event_date": row["date"],
                    "announced_at": context.cutoff.isoformat(),
                    "observed_at": context.cutoff.isoformat(),
                    "source": source,
                    "status": status,
                    "details": row.get("details", {}),
                }
                context.remember(record)
                live_ids.append(record["id"])
            upcoming_events = upcoming(context.records, ticker, context.cutoff.date(), context.cutoff)
        except DataError as exc:
            warnings.append(str(exc))

        earnings_dates = [event.event_date for event in upcoming_events if event.event_type == "earnings"]
        _add_typical_results_move(ticker, earnings_dates, context, warnings)
        _add_option_implied_range(ticker, earnings_dates, context, warnings)

    if args.event_types is not None:
        upcoming_events = [event for event in upcoming_events if event.event_type in args.event_types]
    if not upcoming_events and not live_ids:
        return ToolResult(status="unavailable", source="events",
                          warnings=warnings or ["No configured event-calendar provider returned a timestamped record."])

    ids = list(dict.fromkeys([event.id for event in upcoming_events]))
    ids.extend([i for i in live_ids if i not in ids])
    ids.extend([
        record_id for record_id, record in context.records.items()
        if record.get("kind") == "calc" and record.get("ticker") == ticker
        and record.get("formula") in ("typical_results_day_move", "option_implied_range")
    ])
    return ToolResult(
        status="ok" if upcoming_events or live_ids else "partial",
        data={"ticker": ticker,
              "events": [event.model_dump(mode="json") for event in upcoming_events],
              "market_view_record_ids": [
                  record_id for record_id, record in context.records.items()
                  if record.get("kind") == "calc" and record.get("ticker") == ticker
                  and record.get("formula") in ("typical_results_day_move", "option_implied_range")
              ]},
        ids=ids,
        source="host event records",
        warnings=warnings,
    )


def _add_typical_results_move(ticker: str, earnings_dates: list[date], context: ToolContext,
                              warnings: list[str]) -> None:
    cik = next((record.get("cik") for record in context.records.values()
                if record.get("kind") == "company" and record.get("ticker") == ticker), None)
    if not cik:
        warnings.append("Typical results-day move unavailable: no company CIK.")
        return
    since = context.cutoff.date() - timedelta(days=3 * 366)
    try:
        filings = sec_filings.search(context.sec, cik, context.cutoff, forms={"8-K"}, since=since)
        dates = sorted({filing.filed for filing in filings if "2.02" in filing.items})
    except Exception as exc:
        warnings.append(f"Typical results-day move unavailable: {exc}")
        return
    if not dates:
        warnings.append("Typical results-day move unavailable: no past 8-K results releases.")
        return
    price_result = get_prices(GetPricesInput(ticker=ticker, start=since, end=context.cutoff.date()), context)
    if price_result.status != "ok":
        warnings.append("Typical results-day move unavailable: " + "; ".join(price_result.warnings))
        return
    price = context.records[price_result.ids[0]]
    rows = {row["date"]: row["adj_close"] for row in price["rows"]}
    ordered = sorted(rows)
    moves = []
    for filing_date in dates:
        index = next((i for i, day in enumerate(ordered) if day >= filing_date.isoformat()), None)
        if index is not None and index > 0:
            prior, current = ordered[index - 1], ordered[index]
            if rows[prior] != 0:
                moves.append(abs(rows[current] / rows[prior] - 1))
    if not moves:
        warnings.append("Typical results-day move unavailable: no matched filing-day closes.")
        return
    value = statistics.median(moves)
    record = {
        "id": make_id("event-results-move", ticker, price["id"], len(moves)),
        "kind": "calc",
        "formula": "typical_results_day_move",
        "ticker": ticker,
        "value": round(value, 8),
        "unit": "ratio",
        "start": ordered[0],
        "end": ordered[-1],
        "issued_at": context.cutoff.isoformat(),
        "inputs": {"prices": price["id"], "earnings_dates": [day.isoformat() for day in dates]},
        "status": "ok",
        "notes": [f"Median absolute close-to-close move across {len(moves)} past 8-K results releases."],
    }
    context.remember(record)


def _add_option_implied_range(ticker: str, earnings_dates: list[date], context: ToolContext,
                              warnings: list[str]) -> None:
    if not hasattr(events_yfinance := events.ADAPTERS.get("yfinance"), "option_expiries"):
        return
    try:
        expiries = events_yfinance.option_expiries(ticker)
        if not expiries:
            warnings.append("Option-implied range unavailable: no live expiries.")
            return
        cutoff = context.cutoff.date()
        hint = next((day for day in earnings_dates if cutoff <= day <= cutoff + timedelta(days=90)), None)
        expiry = min(expiries, key=lambda value: abs(
            (date.fromisoformat(value) - (hint or cutoff)).days))
        snapshot = events_yfinance._option_snapshot(ticker, expiry)
        spot = float(snapshot["spot"])
        if spot <= 0:
            raise ValueError("live spot is not positive")

        def mid(row: dict) -> float:
            bid, ask, last = row.get("bid"), row.get("ask"), row.get("lastPrice")
            if bid is not None and ask is not None and float(bid) > 0 and float(ask) > 0:
                return (float(bid) + float(ask)) / 2
            return float(last or 0)

        call = min(snapshot["calls"], key=lambda row: abs(float(row["strike"]) - spot),
                   default=None)
        put = min(snapshot["puts"], key=lambda row: abs(float(row["strike"]) - spot),
                  default=None)
        if call is None or put is None:
            raise ValueError("no at-the-money call and put")
        straddle = mid(call) + mid(put)
        if straddle <= 0:
            raise ValueError("at-the-money straddle is not positive")
        ratio = straddle / spot
        record = {
            "id": make_id("event-option-range", ticker, expiry, context.cutoff.isoformat()),
            "kind": "calc",
            "formula": "option_implied_range",
            "ticker": ticker,
            "value": round(ratio, 8),
            "unit": "ratio",
            "start": cutoff.isoformat(),
            "end": expiry,
            "issued_at": context.cutoff.isoformat(),
            "inputs": {"spot": round(spot, 8), "straddle": round(straddle, 8),
                       "expiry": expiry, "as_of": context.cutoff.isoformat()},
            "status": "ok",
            "notes": [f"Live yfinance at-the-money call-plus-put straddle to expiry {expiry}; "
                      f"approximate range {max(0, spot-straddle):.2f} to {spot+straddle:.2f}."],
        }
        context.remember(record)
    except Exception as exc:
        warnings.append(f"Option-implied range unavailable: {exc}")


TOOL = Tool(
    "get_events",
    "Read host-owned upcoming earnings, ex-dividend and other event records. "
    "Dates are observations, not forecasts, and are never invented by the model.",
    GetEventsInput,
    run,
    "events",
)
