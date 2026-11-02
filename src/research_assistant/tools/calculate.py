"""calculate: deterministic finance formulas over record IDs from earlier tool results.

The model never passes numbers, only IDs, so every input is a value a tool actually returned.
"""
from datetime import date
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field

from .. import config
from ..finance import fundamentals, risk
from .result import Tool, ToolContext, ToolResult, make_id

ROLES = {
    "ratio": ("numerator", "denominator"),  # margins (operating_income / revenue), debt / equity, ...
    "growth": ("current", "previous"),
    "change_pp": ("current", "previous"),  # two ratio results, e.g. this year's and last year's margin
    "cagr": ("first", "last"),
    "fcf": ("operating_cash_flow", "capex"),
    "market_cap": ("prices", "shares"),
    "pe": ("market_cap", "net_income"),
    "ps": ("market_cap", "revenue"),
    "pb": ("market_cap", "equity"),
    "fcf_yield": ("fcf", "market_cap"),
    "ev": ("market_cap", "debt", "cash"),
    "total_return": ("prices",),
    "volatility": ("prices",),
    "max_drawdown": ("prices",),
    "beta": ("prices", "benchmark"),
}
UNITS = {"ratio": "ratio", "growth": "ratio", "change_pp": "pp", "cagr": "ratio", "fcf": "USD", "market_cap": "USD",
         "pe": "x", "ps": "x", "pb": "x", "fcf_yield": "ratio", "ev": "USD", "total_return": "ratio",
         "volatility": "ratio", "max_drawdown": "ratio", "beta": "x"}
PRICE_FORMULAS = {"total_return", "volatility", "max_drawdown", "beta"}


class CalculateInput(BaseModel):
    formula: Literal[tuple(ROLES)]
    inputs: dict[str, str] = Field(description="Role -> record ID from an earlier result. Roles: " + "; ".join(
        f"{name}: {', '.join(roles)}" for name, roles in ROLES.items()) + ".")


class Rejected(Exception):
    """The inputs can't be combined; the message tells the agent what to fix."""


def _number(record: dict) -> Decimal:
    if record["kind"] not in ("fact", "calc") or record.get("value") is None:
        raise Rejected(f"{record['id']} has no numeric value.")
    return Decimal(record["value"])


def _period(record: dict) -> tuple[date | None, date]:
    start = record.get("start")
    return (date.fromisoformat(start) if start else None), date.fromisoformat(record["end"])


def _label(record: dict) -> str:
    return record.get("metric") or record.get("formula") or record.get("ticker") or record["id"]


def _same_period(a: dict, b: dict) -> list[str]:
    (a_start, a_end), (b_start, b_end) = _period(a), _period(b)
    if a_end != b_end or (a_start and b_start and a_start != b_start):
        raise Rejected(f"{a['id']} ({a_start} to {a_end}) and {b['id']} ({b_start} to {b_end}) cover different periods.")
    if bool(a_start) != bool(b_start):
        return ["Combines a year-end balance with a full-year flow."]
    return []


def _ordered(current: dict, previous: dict, same_metric: bool = True) -> Decimal:
    if same_metric and _label(current) != _label(previous):
        raise Rejected(f"{current['id']} is {_label(current)} but {previous['id']} is {_label(previous)}.")
    days = (_period(current)[1] - _period(previous)[1]).days
    if days <= 0:
        raise Rejected(f"{current['id']} must end after {previous['id']}.")
    return Decimal(days) / Decimal("365.25")


def _closes(series: dict, field: str = "adj_close") -> dict[str, float]:
    if series["kind"] != "prices":
        raise Rejected(f"{series['id']} is not a price series from get_prices.")
    return {row["date"]: row[field] for row in series["rows"] if row.get(field) is not None}


def _compute(formula: str, r: dict[str, dict]):
    """Returns (outcome, start, end, notes)."""
    notes: list[str] = []
    if formula in PRICE_FORMULAS:
        closes = _closes(r["prices"])
        dates = sorted(closes)
        values = [closes[d] for d in dates]
        start, end = (dates[0], dates[-1]) if dates else (None, None)
        if formula == "total_return":
            return risk.total_return(values), start, end, notes
        if formula == "volatility":
            return risk.volatility(values, config.TRADING_DAYS_PER_YEAR), start, end, notes
        if formula == "max_drawdown":
            return risk.max_drawdown(values), start, end, notes
        if r["prices"]["source"] != r["benchmark"]["source"]:
            raise Rejected("Beta needs both series from the same provider; fetch them again with one provider.")
        return risk.beta(closes, _closes(r["benchmark"])), start, end, notes
    if formula == "market_cap":
        raw = _closes(r["prices"], "close")
        if not raw:
            raise Rejected(f"{r['prices']['id']} has no as-traded close.")
        last = max(raw)
        shares_end = _period(r["shares"])[1]
        notes.append(f"As-traded close on {last} x shares outstanding on {shares_end}.")
        if abs((date.fromisoformat(last) - shares_end).days) > 120:
            notes.append("The price and share count are more than 120 days apart.")
        outcome = fundamentals.market_cap(Decimal(str(raw[last])), _number(r["shares"]))
        return outcome, None, date.fromisoformat(last), notes
    if formula in ("ratio", "fcf", "pe", "ps", "pb", "fcf_yield"):
        a, b = (r[role] for role in ROLES[formula])
        a_value, b_value = _number(a), _number(b)
        if formula in ("ratio", "fcf"):
            notes += _same_period(a, b)
            if a.get("unit") != b.get("unit"):
                raise Rejected(f"{a['id']} is in {a.get('unit')} but {b['id']} is in {b.get('unit')}.")
        else:
            notes.append(f"Market value on {r['market_cap']['end']} against {_label(b if formula != 'fcf_yield' else a)} "
                         f"for the period ending {(b if formula != 'fcf_yield' else a)['end']}.")
        start, end = _period(a)
        if formula == "ratio":
            return fundamentals.ratio(a_value, b_value), start, end, notes
        if formula == "fcf":
            return fundamentals.free_cash_flow(a_value, b_value), start, end, notes
        if formula == "fcf_yield":
            return fundamentals.ratio(a_value, b_value, "FCF yield"), *_period(b), notes
        return fundamentals.multiple(a_value, b_value, formula.upper()), *_period(a), notes
    if formula == "ev":
        mc, debt, cash = r["market_cap"], r["debt"], r["cash"]
        notes += _same_period(debt, cash)
        return fundamentals.enterprise_value(_number(mc), _number(debt), _number(cash)), None, _period(mc)[1], notes
    current, previous = (r["current"], r["previous"]) if "current" in r else (r["last"], r["first"])
    years = _ordered(current, previous, same_metric=formula != "change_pp")
    start, end = _period(previous)[0], _period(current)[1]
    if formula == "growth":
        if not Decimal("0.9") <= years <= Decimal("1.1"):
            notes.append(f"The two periods end {float(years):.2f} years apart, not one.")
        return fundamentals.growth(_number(current), _number(previous)), start, end, notes
    if formula == "change_pp":
        if current.get("unit") != "ratio" or previous.get("unit") != "ratio":
            raise Rejected("change_pp needs two ratio results (for example two margins).")
        return fundamentals.change_pp(_number(current), _number(previous)), start, end, notes
    return fundamentals.cagr(_number(previous), _number(current), years), start, end, notes


def _rounded(value, unit: str):
    if value is None or isinstance(value, float):
        return None if value is None else round(value, 6)
    return str(value.quantize(Decimal(1) if unit == "USD" else Decimal("0.000001")))


def run(args: CalculateInput, context: ToolContext) -> ToolResult:
    roles = ROLES[args.formula]
    missing = [role for role in roles if role not in args.inputs]
    unknown = [i for i in args.inputs.values() if i not in context.records]
    if missing or unknown:
        problems = ([f"{args.formula} needs inputs: {', '.join(roles)} (missing {', '.join(missing)})."] if missing else [])
        problems += [f"{i} is not an ID returned earlier in this run." for i in unknown]
        return ToolResult(status="invalid", source="calculate", warnings=problems)
    records = {role: context.records[args.inputs[role]] for role in roles}
    try:
        outcome, start, end, notes = _compute(args.formula, records)
    except Rejected as exc:
        return ToolResult(status="invalid", source="calculate", warnings=[str(exc)])
    unit = UNITS[args.formula]
    record = {"id": make_id("calc", args.formula, *(f"{role}={args.inputs[role]}" for role in roles)), "kind": "calc",
              "formula": args.formula, "inputs": {role: args.inputs[role] for role in roles},
              "value": _rounded(outcome.value, unit), "unit": unit,
              "start": start.isoformat() if isinstance(start, date) else start,
              "end": end.isoformat() if isinstance(end, date) else end,
              "status": "ok" if outcome.value is not None else "unavailable", "reason": outcome.reason,
              "notes": notes + ([outcome.note] if outcome.note else [])}
    context.remember(record)
    return ToolResult(status="ok" if outcome.value is not None else "unsupported", data=record, ids=[record["id"]],
                      source="calculate", warnings=[outcome.reason] if outcome.reason else [])


TOOL = Tool("calculate", "Compute a finance formula from IDs returned by other tools (never from typed numbers): "
            "ratio (margins), growth, change_pp, cagr, fcf, market_cap, pe, ps, pb, fcf_yield, ev, total_return, "
            "volatility, max_drawdown, beta. Returns a calc ID to cite.", CalculateInput, run, "calculate")
