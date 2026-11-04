"""screen: pass / fail / unknown filters over a universe from SEC frames, ranked by a stated rule (REFERENCE §4).

Unknown never passes. Ties break on CIK, a stable ID, never alphabetically.
"""
import operator
from datetime import timedelta
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field

from .. import config
from ..data import companies, sec_facts
from ..data.errors import DataError
from ..data.sec import cik10
from ..finance import fundamentals
from .result import Tool, ToolContext, ToolResult, make_id

BASE = {name: sec_facts.CONCEPTS[name] for name in ("revenue", "operating_income", "net_income", "operating_cash_flow", "capex")}
# What each screen metric needs from the frames: ("revenue", 0) is this year's revenue, ("revenue", -1) last year's.
NEEDS = {"revenue": [("revenue", 0)], "operating_income": [("operating_income", 0)], "net_income": [("net_income", 0)],
         "operating_cash_flow": [("operating_cash_flow", 0)],
         "fcf": [("operating_cash_flow", 0), ("capex", 0)],
         "operating_margin": [("operating_income", 0), ("revenue", 0)], "net_margin": [("net_income", 0), ("revenue", 0)],
         "fcf_margin": [("operating_cash_flow", 0), ("capex", 0), ("revenue", 0)],
         "revenue_growth": [("revenue", 0), ("revenue", -1)]}
Metric = Literal[tuple(NEEDS)]
OPERATORS = {">": operator.gt, ">=": operator.ge, "<": operator.lt, "<=": operator.le}


class Filter(BaseModel):
    metric: Metric
    op: Literal[">", ">=", "<", "<="]
    value: float = Field(description="Ratios as fractions: an operating margin above 25% is 0.25.")


class ScreenInput(BaseModel):
    universe: list[str] | None = Field(None, description="Tickers or CIKs to screen; omit for every SEC filer in the frame.")
    sic_prefixes: list[str] | None = Field(None, description='Keep SIC industry codes starting with these, e.g. ["357", "7372"].')
    filters: list[Filter] = Field(default_factory=list)
    rank_by: Metric
    descending: bool = True
    top_k: int | None = Field(None, ge=1, description=f"Candidates to return (default {config.SCREEN_DEFAULT_TOP_K}).")
    year: int | None = Field(None, description="Calendar year of SEC data; default: the latest complete one before the cutoff.")


def _value(metric: str, base: dict) -> Decimal | None:
    get = base.get
    if metric in ("revenue", "operating_income", "net_income", "operating_cash_flow"):
        return get((metric, 0))
    if None in [get(need) for need in NEEDS[metric]]:
        return None
    if metric == "fcf":
        return fundamentals.free_cash_flow(get(("operating_cash_flow", 0)), get(("capex", 0))).value
    if metric == "revenue_growth":
        return fundamentals.growth(get(("revenue", 0)), get(("revenue", -1))).value
    numerator = {"operating_margin": get(("operating_income", 0)), "net_margin": get(("net_income", 0)),
                 "fcf_margin": _value("fcf", base)}[metric]
    return fundamentals.ratio(numerator, get(("revenue", 0))).value


def run(args: ScreenInput, context: ToolContext) -> ToolResult:
    if context.historical:
        return ToolResult(status="invalid", source="SEC frames", warnings=[
            f"screen can't run as of a past cutoff ({context.cutoff.date()}): SEC frames hold today's latest-filed "
            "values, which may come from filings after it. Check each company with get_financials instead."])
    latest = (context.cutoff.date() - timedelta(days=config.SCREEN_FRAME_LAG_DAYS)).year - 1
    year = args.year or latest
    if year > latest:
        return ToolResult(status="invalid", source="SEC frames", warnings=[
            f"Calendar year {year} is not complete in SEC data before the cutoff; the latest is {latest}."])
    metrics = {f.metric for f in args.filters} | {args.rank_by}
    wanted = {need for metric in metrics for need in NEEDS[metric]}
    frames = {need: sec_facts.frame(context.sec, BASE[need[0]], year + need[1]) for need in sorted(wanted)}
    warnings = [f"SEC frames hold each company's latest-filed value for the fiscal year closest to calendar {year} "
                "(restated, not point-in-time) and may include filings after the cutoff. Verify shortlisted companies "
                "with get_financials."]
    listed = companies.listed_companies(context.sec)
    if args.universe:
        ciks = []
        for entry in args.universe:
            text = entry.strip()
            cik = cik10(text) if text.isdigit() else next(
                (c.cik for c in listed.values() if companies.normalize_ticker(text) in c.tickers), None)
            if cik is None:
                warnings.append(f"{entry}: no SEC filer with that ticker; left out.")
            elif cik not in ciks:
                ciks.append(cik)
    else:
        ciks = sorted({cik for values in frames.values() for cik in values})
    rows = []
    for cik in ciks:
        base = {need: frames[need].get(cik, {}).get("value") for need in wanted}
        values = {metric: _value(metric, base) for metric in metrics}
        checks = []
        for f in args.filters:
            value = values[f.metric]
            checks.append(("unknown", f"{f.metric} unavailable") if value is None else
                          ("pass" if OPERATORS[f.op](value, Decimal(str(f.value))) else "fail", f"{f.metric} {f.op} {f.value}"))
        name = next((frames[n][cik]["name"] for n in frames if cik in frames[n]), None) or getattr(listed.get(cik), "name", None)
        rows.append({"cik": cik, "name": name, "tickers": list(getattr(listed.get(cik), "tickers", ())),
                     "values": values, "checks": checks})
    for row in rows:
        if args.sic_prefixes and all(c[0] == "pass" for c in row["checks"]):
            try:
                sic = companies.profile(context.sec, row["cik"])["sic"]
                row["sic"] = sic
                passed = sic is not None and str(sic).startswith(tuple(args.sic_prefixes))
                row["checks"].append(("pass" if passed else "fail", f"SIC {sic} starts with {'/'.join(args.sic_prefixes)}"))
            except DataError:
                row["checks"].append(("unknown", "SIC industry code unavailable"))
        states = {c[0] for c in row["checks"]}
        row["eligibility"] = "fail" if "fail" in states else "unknown" if "unknown" in states else "pass"
    eligible = [r for r in rows if r["eligibility"] == "pass"]
    ranked = [r for r in eligible if r["values"][args.rank_by] is not None]
    ranked.sort(key=lambda r: r["cik"])
    ranked.sort(key=lambda r: r["values"][args.rank_by], reverse=args.descending)  # stable: ties stay in CIK order
    top_k = args.top_k or config.SCREEN_DEFAULT_TOP_K
    counts = {"screened": len(rows), "eligible": len(eligible), "failed": sum(r["eligibility"] == "fail" for r in rows),
              "unknown": sum(r["eligibility"] == "unknown" for r in rows), "unranked": len(eligible) - len(ranked),
              "returned": min(top_k, len(ranked))}
    if counts["unranked"]:
        warnings.append(f"{counts['unranked']} eligible companies have no {args.rank_by} and could not be ranked.")
    if not args.universe:
        warnings.append(f"The universe is every company in SEC's {year} frames, today's filers only (survivorship bias).")

    def shown(row, rank=None):
        return {"rank": rank, "cik": row["cik"], "name": row["name"], "tickers": row["tickers"], "sic": row.get("sic"),
                "values": {m: (None if v is None else str(round(v, 6))) for m, v in row["values"].items()},
                "eligibility": row["eligibility"], "checks": [f"{state}: {why}" for state, why in row["checks"]]}
    spec = args.model_dump(mode="json") | {"year": year, "top_k": top_k}
    record = {"id": make_id("screen", spec, year), "kind": "screen", "spec": spec, "counts": counts,
              "rows": [shown(r) for r in rows]}
    context.remember(record)
    candidates = [shown(r, rank) for rank, r in enumerate(ranked[:top_k], 1)]
    return ToolResult(status="ok", data={"id": record["id"], "spec": spec, "counts": counts, "candidates": candidates},
                      ids=[record["id"]], source="SEC frames", warnings=warnings)


TOOL = Tool("screen", "Screen companies on annual SEC data (revenue, growth, margins, net income, free cash flow, SIC "
            "industry) with pass/fail/unknown filters, then rank the passes by one metric. Unknown never passes. "
            "Returns counts and the top candidates; verify them with get_financials. Live runs only: refused when the "
            "run has a past cutoff.", ScreenInput, run, "SEC frames")
