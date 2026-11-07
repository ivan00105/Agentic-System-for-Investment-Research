"""calculate: deterministic finance formulas over record IDs from earlier tool results.

The model never passes numbers, only IDs, so every input is a value a tool actually returned.
"""
import math
from datetime import date
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field

from .. import config
from ..finance import Outcome, fundamentals, risk
from . import share_basis
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
    "sharpe": ("prices", "risk_free"),
    "relative_return": ("prices", "benchmark"),  # e.g. against the sector ETF from get_peers
}
# Roles a formula takes only sometimes: a 20-F/40-F share count needs its filing's ADS ratio.
OPTIONAL_ROLES = {"market_cap": ("ads_ratio",)}
UNITS = {"ratio": "ratio", "growth": "ratio", "change_pp": "pp", "cagr": "ratio", "fcf": "USD", "market_cap": "USD",
         "pe": "x", "ps": "x", "pb": "x", "fcf_yield": "ratio", "ev": "USD", "total_return": "ratio",
         "volatility": "ratio", "max_drawdown": "ratio", "beta": "x", "sharpe": "x", "relative_return": "pp"}
PRICE_FORMULAS = {"total_return", "volatility", "max_drawdown", "beta", "sharpe", "relative_return"}
# A Sharpe ratio's risk-free rate: get_macro's average 3-month T-bill rate over the price series' dates.
RISK_FREE_METRIC = "tbill_3m_avg"
# A 10-K/10-Q cover count is the listed common stock; a 20-F/40-F filer's US quote is usually an ADS of N shares.
DOMESTIC_SHARE_FORMS = {"10-K", "10-K/A", "10-Q", "10-Q/A"}
ADS_RATIO_METRIC = share_basis.METRIC
# What each named USD input must measure: a get_financials metric, or calculate's fcf. Ratio's roles stay open.
USD_ROLES = {"net_income": "net_income", "revenue": "revenue", "equity": "stockholders_equity", "debt": "long_term_debt",
             "cash": "cash", "operating_cash_flow": "operating_cash_flow", "capex": "capex", "fcf": "fcf"}


class CalculateInput(BaseModel):
    formula: Literal[tuple(ROLES)]
    inputs: dict[str, str] = Field(description="Role -> record ID from an earlier result. Roles: " + "; ".join(
        f"{name}: {', '.join(roles)}" for name, roles in ROLES.items()) + ". market_cap on a 20-F/40-F share count "
        f"also takes ads_ratio: the {ADS_RATIO_METRIC} fact get_financials gives with it, from the same filing.")


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
    # A blank (None or NaN) close is unknown and left out, never treated as a price.
    return {row["date"]: row[field] for row in series["rows"]
            if isinstance(row.get(field), (int, float)) and math.isfinite(row[field])}


def _check_roles(r: dict[str, dict]) -> None:
    """Each named role gets the kind of record it means, so revenue can't stand in for a share count."""
    for role, record in r.items():
        if role in ("prices", "benchmark") and record["kind"] != "prices":
            raise Rejected(f"{record['id']} is not a price series from get_prices ({role}).")
        # A weighted-average count (diluted_shares) is a year's average, not the shares outstanding on a day.
        if role == "shares" and (record["kind"] != "fact" or record.get("metric") != "shares_outstanding"):
            raise Rejected(f"{record['id']} is {_label(record)} in {record.get('unit')}, not a share count from "
                           "shares_outstanding (shares).")
        if role in USD_ROLES and (record["kind"] not in ("fact", "calc") or record.get("unit") != "USD"):
            raise Rejected(f"{record['id']} is {_label(record)} in {record.get('unit')}, not a USD amount ({role}).")
        if role in USD_ROLES and _label(record) != USD_ROLES[role]:
            raise Rejected(f"{record['id']} is {_label(record)}, not {USD_ROLES[role]} ({role}).")
        if role == "risk_free" and (record["kind"] != "fact" or record.get("metric") != RISK_FREE_METRIC):
            raise Rejected(f"{record['id']} is {_label(record)}, not get_macro's tbill_3m average over the price "
                           "series' dates (risk_free).")
        if role == "ads_ratio" and (record["kind"] != "fact" or record.get("metric") != ADS_RATIO_METRIC):
            raise Rejected(f"{record['id']} is {_label(record)}, not get_financials' {ADS_RATIO_METRIC} (ads_ratio).")
        if role == "market_cap" and (record["kind"] != "calc" or record.get("formula") != "market_cap"):
            raise Rejected(f"{record['id']} is {_label(record)}, not a market_cap result from calculate (market_cap).")


def _company(formula: str, r: dict[str, dict]) -> tuple[str | None, list[str]]:
    """The one company every input describes. A beta's benchmark and the risk-free rate describe no company."""
    ciks = {record.get("cik") for role, record in r.items() if role not in ("benchmark", "risk_free")}
    known = sorted(ciks - {None})
    if len(known) > 1:
        raise Rejected(f"The inputs belong to different companies (CIK {', '.join(known)}); calculate each company "
                       "separately and compare the results.")
    notes = ["Not every input could be tied to a company (e.g. an unmatched ticker); check they describe the same one."
             if known and None in ciks else None]
    return (known[0] if known else None), [n for n in notes if n]


def _split_factor(series: dict, shares_day: date, price_day: date) -> tuple[Decimal, list[str]]:
    """Splits between the share count and the price, so both are on one share basis (2-for-1: shares x 2)."""
    if price_day < shares_day:
        return Decimal(1), [f"The share count ({shares_day}) is later than the price ({price_day}); splits between "
                            "them could not be checked."]
    notes = []
    first = min(date.fromisoformat(row["date"]) for row in series["rows"])
    if first > shares_day:
        notes.append(f"The price series starts on {first}, after the share count; splits in between could not be checked.")
    splits = [(row["date"], Decimal(str(row["split"]))) for row in series["rows"]
              if row.get("split") not in (None, 0, 1) and shares_day < date.fromisoformat(row["date"]) <= price_day]
    factor = Decimal(1)
    for _, ratio in splits:
        factor *= ratio
    if splits:
        notes.append(f"Share count multiplied by {factor} for the split(s) on {', '.join(d for d, _ in splits)}, after "
                     "the share-count date, to match the as-traded price.")
    return factor, notes


def _same_window(rate: dict, start: str | None, end: str | None) -> None:
    """The risk-free average must cover the price series' dates, give or take a few holidays."""
    slack = config.RISK_FREE_WINDOW_SLACK_DAYS

    def later(a: str, b: str) -> int:  # days a is after b
        return (date.fromisoformat(a) - date.fromisoformat(b)).days
    if start and rate.get("start") and all(abs(later(a, b)) <= slack for a, b in ((rate["start"], start), (rate["end"], end))):
        return
    covers = f"{rate['id']} covers {rate.get('start')} to {rate.get('end')}"
    if start and rate.get("start") and later(rate["start"], start) >= -slack and later(end, rate["end"]) >= -slack:
        # Inside the price window but shorter: asking get_macro again for the same dates gives the same days.
        raise Rejected(f"{covers}, fewer days than the prices ({start} to {end}). If get_macro was asked for the price "
                       f"dates, it has no rate for the rest: shorten the price series to {rate['start']} to "
                       f"{rate['end']}, or say the Sharpe ratio is unavailable; if not, call get_macro with series "
                       f"tbill_3m, start {start} and end {end}.")
    raise Rejected(f"{covers}, but the prices cover {start} to {end}; call get_macro with series tbill_3m, start {start} "
                   f"and end {end}.")


def _market_cap(r: dict[str, dict], warnings: list[str]):
    """As-traded close x shares. A 20-F/40-F count is of ordinary shares, so the close of a US-listed share (often an
    ADS) is first divided by the ordinary shares it stands for, read from the same filing."""
    raw = _closes(r["prices"], "close")
    if not raw:
        raise Rejected(f"{r['prices']['id']} has no as-traded close.")
    last = max(raw)
    day = date.fromisoformat(last)
    shares, ratio, form = r["shares"], r.get("ads_ratio"), r["shares"].get("form")
    shares_end = _period(shares)[1]
    if form in DOMESTIC_SHARE_FORMS:
        if ratio:
            raise Rejected(f"{shares['id']} is from a {form}, whose cover counts the listed shares; drop ads_ratio.")
        per_listed, notes = Decimal(1), [f"As-traded close on {last} x shares outstanding on {shares_end}."]
    elif form in share_basis.FOREIGN_FORMS and ratio:
        if ratio.get("accession") != shares.get("accession"):
            raise Rejected(f"{ratio['id']} is from filing {ratio.get('accession')} but {shares['id']} is from "
                           f"{shares.get('accession')}; use the {ADS_RATIO_METRIC} fact from the share count's filing.")
        per_listed = _number(ratio)
        notes = [f"As-traded close of a US-listed share on {last} / {ratio['value']} ordinary shares per listed share "
                 f"x {shares['value']} ordinary shares outstanding on {shares_end}; the ratio is from the same {form} "
                 f"({shares.get('accession')}): \"{ratio.get('title')}\"."]
        filed = date.fromisoformat(shares["filed"])
        if (day - filed).days > config.SHARE_FILING_MAX_AGE_DAYS:
            notes.append(f"The share count and ADS ratio come from a {form} filed {filed}, more than a year before "
                         f"the price ({last}); either may have changed since.")
            warnings.append(notes[-1])
    else:
        why = (f"the share count comes from a {form}, and a foreign filer's US quote is often a depositary share (ADS) "
               f"of several ordinary shares; pass ads_ratio, the {ADS_RATIO_METRIC} fact get_financials gives for "
               f"filing {shares.get('accession')}" if form in share_basis.FOREIGN_FORMS else
               f"the share count comes from a {form}" if form else "the share count's filing form is unknown")
        return Outcome(None, f"Market cap unsupported: {why}, so the share basis of the price can't be confirmed."),             None, day, []
    if abs((day - shares_end).days) > 120:
        notes.append("The price and share count are more than 120 days apart.")
    factor, split_notes = _split_factor(r["prices"], shares_end, day)
    outcome = fundamentals.market_cap(Decimal(str(raw[last])) / per_listed, _number(shares) * factor)
    return outcome, None, day, notes + split_notes


def _compute(formula: str, r: dict[str, dict], warnings: list[str]):
    """Returns (outcome, start, end, notes); a caveat the caller must see goes into `warnings` too."""
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
        if formula == "sharpe":
            _same_window(r["risk_free"], start, end)
            rate = float(_number(r["risk_free"]))
            return risk.sharpe(values, rate, config.TRADING_DAYS_PER_YEAR), start, end, notes
        if r["prices"]["source"] != r["benchmark"]["source"]:
            raise Rejected(f"{formula} needs both series from the same provider; fetch them again with one provider.")
        if formula == "relative_return":
            return risk.relative_return(closes, _closes(r["benchmark"])), start, end, notes
        return risk.beta(closes, _closes(r["benchmark"])), start, end, notes
    if formula == "market_cap":
        return _market_cap(r, warnings)
    if "market_cap" in r and r["market_cap"].get("value") is None:
        return Outcome(None, f"No market cap ({r['market_cap'].get('reason')})"), None, _period(r["market_cap"])[1], notes
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
    roles = ROLES[args.formula] + tuple(r for r in OPTIONAL_ROLES.get(args.formula, ()) if r in args.inputs)
    missing = [role for role in roles if role not in args.inputs]
    unknown = [i for i in args.inputs.values() if i not in context.records]
    if missing or unknown:
        problems = ([f"{args.formula} needs inputs: {', '.join(roles)} (missing {', '.join(missing)})."] if missing else [])
        problems += [f"{i} is not an ID returned earlier in this run." for i in unknown]
        return ToolResult(status="invalid", source="calculate", warnings=problems)
    records = {role: context.records[args.inputs[role]] for role in roles}
    caveats: list[str] = []
    try:
        _check_roles(records)
        cik, company_notes = _company(args.formula, records)
        outcome, start, end, notes = _compute(args.formula, records, caveats)
    except Rejected as exc:
        return ToolResult(status="invalid", source="calculate", warnings=[str(exc)])
    notes += company_notes
    converted = [r for r in records.values() if r.get("reported_unit")]
    notes += [f"{r['id']} ({_label(r)}) is converted from {r['reported_unit']} at {r.get('fx_rate')} per US dollar "
              f"({r.get('fx_source')})." for r in converted]
    if args.formula in ("growth", "cagr", "change_pp") and converted:
        notes.append("The inputs are converted at each year's own rates, so the change includes exchange-rate moves.")
    unit = UNITS[args.formula]
    record = {"id": make_id("calc", args.formula, *(f"{role}={args.inputs[role]}" for role in roles)), "kind": "calc",
              "cik": cik, "formula": args.formula, "inputs": {role: args.inputs[role] for role in roles},
              "value": _rounded(outcome.value, unit), "unit": unit,
              "start": start.isoformat() if isinstance(start, date) else start,
              "end": end.isoformat() if isinstance(end, date) else end,
              "status": "ok" if outcome.value is not None else "unavailable", "reason": outcome.reason,
              "notes": notes + ([outcome.note] if outcome.note else [])}
    context.remember(record)
    return ToolResult(status="ok" if outcome.value is not None else "unsupported", data=record, ids=[record["id"]],
                      source="calculate", warnings=([outcome.reason] if outcome.reason else []) + caveats)


TOOL = Tool("calculate", "Compute a finance formula from IDs returned by other tools (never from typed numbers): "
            "ratio (margins), growth, change_pp, cagr, fcf, market_cap, pe, ps, pb, fcf_yield, ev, total_return, "
            "volatility, max_drawdown, beta, sharpe, relative_return. Returns a calc ID to cite.", CalculateInput, run, "calculate")
