"""get_macro: the risk-free rate, Treasury yields, inflation and unemployment as known at the cutoff, and the release
dates of major US data after it (REFERENCE §10). Every value is a citable fact; rates are fractions (4% = 0.04)."""
import calendar
import json
from datetime import date, timedelta
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field

from .. import config
from ..data import macro, prices
from ..data.errors import DataError
from .result import Tool, ToolContext, ToolResult, make_id

CALENDAR_URL = "https://fred.stlouisfed.org/releases/calendar"


class GetMacroInput(BaseModel):
    series: list[Literal[tuple(macro.SERIES)]] | None = Field(None, description=(
        "Default: every series a configured provider has. tbill_3m is the risk-free rate."))
    start: date | None = Field(None, description="With end, also each series' average over these dates. For a "
                               "sharpe calculation, use the price series' first and last day.")
    end: date | None = Field(None, description="Last day of the average; default and maximum: the research cutoff.")
    horizon_days: int | None = Field(None, ge=0, le=config.MACRO_MAX_HORIZON_DAYS, description=(
        "Release dates of major US data (CPI, jobs report, GDP, PCE, FOMC decisions) from the cutoff day through the "
        f"next N days; default {config.MACRO_RELEASE_HORIZON_DAYS}, 0 for none."))


def _ratio(values: list[str]) -> Decimal:
    """The mean of published percentages, as a fraction."""
    return (sum(Decimal(v) for v in values) / len(values) / 100).quantize(Decimal("0.000001"))


def _fact(name: str, provider: str, as_of: date, start: str | None, end: str, value: Decimal, metric: str | None = None,
          **extra) -> dict:
    adapter, metric = macro.ADAPTERS[provider], metric or name
    vintage = as_of.isoformat() if provider == "fred" else None  # Treasury doesn't revise, so it has no vintages
    record = {"kind": "fact", "cik": None, "metric": metric, "label": macro.SERIES[name][0], "value": str(value),
              "unit": "ratio", "start": start, "end": end, "source": adapter.LABEL, "series_id": adapter.SERIES[name][0],
              "definition": adapter.SERIES[name][-1], "url": adapter.url(name), "vintage": vintage, **extra}
    return {"id": make_id("fact", "macro", provider, metric, start, end, vintage, value), **record}


def _last_day(name: str, day: date) -> date:
    """A monthly value covers its whole month."""
    return day.replace(day=calendar.monthrange(day.year, day.month)[1]) if macro.SERIES[name][1] == "monthly" else day


def _observation(name: str, provider: str, as_of: date, row: dict) -> dict:
    """The latest value."""
    day = date.fromisoformat(row["date"])
    monthly = macro.SERIES[name][1] == "monthly"
    return _fact(name, provider, as_of, day.isoformat() if monthly else None, _last_day(name, day).isoformat(),
                 _ratio([row["value"]]))


def _average(name: str, provider: str, as_of: date, rows: list[dict], start: date, end: date) -> dict | None:
    """Dated by the observations it uses, not the dates asked for, so calculate's period check sees a gap."""
    inside = [r for r in rows if start.isoformat() <= r["date"] <= end.isoformat()]
    if not inside:
        return None
    first, last = inside[0]["date"], _last_day(name, date.fromisoformat(inside[-1]["date"])).isoformat()
    note = (f"Average of {len(inside)} {macro.SERIES[name][1]} observations from {inside[0]['date']} to "
            f"{inside[-1]['date']}.")
    return _fact(name, provider, as_of, first, last, _ratio([r["value"] for r in inside]),
                 metric=f"{name}_avg", label=f"{macro.SERIES[name][0]} (average)", observations=len(inside), notes=[note])


def _shown(record: dict) -> dict:
    return {"id": record["id"], "start": record["start"], "end": record["end"], "value": record["value"],
            "percent": str((Decimal(record["value"]) * 100).quantize(Decimal("0.01")))}


def _releases(args: GetMacroInput, context: ToolContext, cache) -> tuple[dict | None, list[str]]:
    horizon = config.MACRO_RELEASE_HORIZON_DAYS if args.horizon_days is None else args.horizon_days
    if not horizon:
        return None, []
    first = context.cutoff.astimezone(prices.NEW_YORK).date()
    last = first + timedelta(days=horizon)
    try:
        rows, provider = macro.releases(first, last, cache)
    except DataError as exc:
        return None, [f"Release dates unavailable: {exc}"]
    notes = [f"Times aren't listed, so a release on {first} may already be out at the cutoff."]
    if context.historical:
        notes.append("This is the release calendar as FRED shows it today; a date may have moved since the cutoff.")
    record = {"id": make_id("calendar", provider, first, last, json.dumps(rows, sort_keys=True)), "kind": "calendar",
              "source": macro.ADAPTERS[provider].LABEL, "start": first.isoformat(), "end": last.isoformat(),
              "releases": rows, "url": CALENDAR_URL, "notes": notes}
    context.remember(record)
    return record, notes


def run(args: GetMacroInput, context: ToolContext) -> ToolResult:
    as_of = prices.last_known_day(context.cutoff)  # a day's rates are published after the close, like prices
    warnings: list[str] = []
    end = args.end or as_of
    if end > as_of:
        warnings.append(f"End date moved from {end} to {as_of}: later values were not public at the cutoff.")
        end = as_of
    if args.start and args.start > end:
        return ToolResult(status="invalid", source="macro", warnings=[f"Start {args.start} is after end {end}."])
    asked = list(dict.fromkeys(args.series or []))
    available = [s for s in macro.SERIES if any(macro.ADAPTERS[n].configured() for n in macro.having(s))]
    names = asked or available
    if not asked and (left := [s for s in macro.SERIES if s not in available]):
        warnings.append(f"Not available without {' or '.join(dict.fromkeys(e for s in left for e in macro.needs(s)))}: "
                        f"{', '.join(left)}.")
    cache = context.cache("macro_cache")
    first = as_of - timedelta(days=config.MACRO_LATEST_LOOKBACK_DAYS)
    shown, ids, missing, sources, notes = [], [], [], [], []
    for name in names:
        try:
            rows, provider, skipped = macro.fetch(name, min(first, args.start or first), as_of, as_of, cache)
        except DataError as exc:
            missing.append(name)
            warnings.append(f"{name}: {exc}")
            continue
        notes += skipped
        latest = _observation(name, provider, as_of, rows[-1])
        entry = {"name": name, "label": macro.SERIES[name][0], "definition": latest["definition"],
                 "source": latest["source"] + ("" if macro.having(name)[:1] == [provider] else " (fallback)"),
                 "latest": _shown(latest)}
        found = [latest]
        if args.start:
            average = _average(name, provider, as_of, rows, args.start, end)
            entry["average"] = average and _shown(average) | {"observations": average["observations"]}
            if average:
                found.append(average)
            else:
                warnings.append(f"{name}: no observations between {args.start} and {end}.")
        for record in found:
            ids.append(context.remember(record))
        shown.append(entry)
        sources.append(entry["source"])
    calendar_record, calendar_notes = _releases(args, context, cache)
    warnings += list(dict.fromkeys(notes)) + calendar_notes
    data = {"as_of": as_of.isoformat(), "series": shown, "rates": "Values are fractions: 0.0412 is 4.12%."}
    if calendar_record:
        ids.append(calendar_record["id"])
        data["releases"] = {"id": calendar_record["id"], "start": calendar_record["start"], "end": calendar_record["end"],
                            "dates": [{"date": r["date"], "name": r["name"]} for r in calendar_record["releases"]]}
        sources.append(calendar_record["source"])
    asked_releases = args.horizon_days is not None and args.horizon_days > 0
    if not shown and not calendar_record:
        status = "unavailable"
    elif (asked and missing) or (asked_releases and not calendar_record):
        status = "partial"
    else:
        status = "ok"
    return ToolResult(status=status, data=data, ids=ids, source=", ".join(dict.fromkeys(sources)) or "macro",
                      warnings=warnings)


TOOL = Tool("get_macro", "Rates and the economy as known at the research cutoff: the 3-month T-bill (risk-free rate), "
            "2- and 10-year Treasury yields, fed funds, CPI inflation and unemployment, each a fact ID to cite; with "
            "start and end, also each one's average over those dates (tbill_3m's average is calculate's risk_free for "
            "sharpe). Also lists release dates of major US data (CPI, jobs, GDP, PCE, FOMC) after the cutoff.",
            GetMacroInput, run, "macro")
