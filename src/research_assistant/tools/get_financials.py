"""get_financials: multi-year annual fundamentals from SEC companyfacts, each value citable by ID."""
from typing import Literal

from pydantic import BaseModel, Field

from .. import config
from ..data import companies, sec_facts
from ..data.sec import cik10
from .result import Tool, ToolContext, ToolResult, make_id

Metric = Literal[tuple(sec_facts.CONCEPTS)]
NOT_REPORTED_BY_FINANCIALS = {"operating_income", "gross_profit"}


class GetFinancialsInput(BaseModel):
    cik: str = Field(pattern=r"^[0-9]{1,10}$", description="The company's CIK from find_company.")
    metrics: list[Metric] | None = Field(None, description="Metrics to return; omit for all of them.")
    years: int | None = Field(None, ge=1, description=f"Most recent fiscal years to return (default "
                              f"{config.FINANCIALS_DEFAULT_YEARS}); older years are counted in a warning.")


def run(args: GetFinancialsInput, context: ToolContext) -> ToolResult:
    cik = cik10(args.cik)
    response = context.sec.companyfacts(cik)
    payload = response.json()
    source = "SEC companyfacts"
    if "us-gaap" not in sec_facts.taxonomies(payload):
        kind = "IFRS (a foreign private issuer)" if "ifrs-full" in sec_facts.taxonomies(payload) else "no US GAAP taxonomy"
        return ToolResult(status="unsupported", source=source, data={"cik": cik, "name": payload.get("entityName")},
                          warnings=[f"{payload.get('entityName', cik)} reports under {kind}; only US GAAP fundamentals are supported."])
    years = args.years or config.FINANCIALS_DEFAULT_YEARS
    year_ends = sec_facts.fiscal_year_ends(payload, context.cutoff)
    kept_ends = sorted(year_ends, reverse=True)[:years]
    oldest = min(kept_ends) if kept_ends else None
    financial = None  # looked up only if a metric is missing
    metrics, ids, warnings = {}, [], []
    for name in args.metrics or list(sec_facts.CONCEPTS):
        concept = sec_facts.CONCEPTS[name]
        facts, problems = sec_facts.select(payload, concept, context.cutoff, year_ends)
        warnings += problems
        shown = [f for f in facts if oldest is not None and f.end >= oldest]
        if concept.kind != "cover":
            shown = shown[:years]
        if len(facts) > len(shown):
            warnings.append(f"{name}: {len(facts) - len(shown)} older values not shown; ask for more years to see them.")
        if not shown and (units := sec_facts.other_units(payload, concept)) and not facts:
            metrics[name] = {"status": "unsupported", "reason": f"Reported in {', '.join(units)}, not {concept.unit}; "
                             "currency conversion is not supported."}
            continue
        if not shown:
            if financial is None:
                financial = companies.profile(context.sec, cik)["financial_sector"]
            unsupported = financial and name in NOT_REPORTED_BY_FINANCIALS
            metrics[name] = {"status": "unsupported" if unsupported else "not_reported", "reason": (
                "Banks, brokers and insurers don't report this line." if unsupported else
                f"No annual value before the cutoff under {', '.join(concept.tags)}.")}
            continue
        values = []
        for fact in shown:
            record = {"id": make_id("fact", cik, fact.tag, fact.start, fact.end, fact.accession, fact.value), "kind": "fact",
                      "cik": cik, "metric": name, "tag": fact.tag, "unit": fact.unit, "value": str(fact.value),
                      "start": fact.start and fact.start.isoformat(), "end": fact.end.isoformat(),
                      "accession": fact.accession, "form": fact.form, "filed": fact.filed.isoformat(),
                      "available_at": sec_facts.available_at(fact.filed).isoformat(), "source_url": response.url,
                      "filing_url": f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{fact.accession.replace('-', '')}/"}
            if fact.original_value is not None:
                record.update(original_value=str(fact.original_value), original_accession=fact.original_accession)
                warnings.append(f"{name} for the period ending {fact.end} was restated: first reported as "
                                f"{fact.original_value} in {fact.original_accession}, now {fact.value}.")
            ids.append(context.remember(record))
            values.append({k: v for k, v in record.items() if k not in ("kind", "cik", "metric", "unit", "source_url")})
        metrics[name] = {"status": "ok", "unit": concept.unit, "values": values}
        if (units := sec_facts.other_units(payload, concept)) and concept.unit == "USD":
            warnings.append(f"{name} is also reported in {', '.join(units)}: the USD figures are probably convenience "
                            "translations at one exchange rate per filing, so changes across years mix exchange rates.")
    ok = [m for m in metrics.values() if m["status"] == "ok"]
    if len(ok) == len(metrics):
        status = "ok"
    elif ok:
        status = "partial"
    else:
        status = "unsupported" if any(m["status"] == "unsupported" for m in metrics.values()) else "not_found"
    data = {"cik": cik, "name": payload.get("entityName"), "fiscal_year_ends": [d.isoformat() for d in kept_ends],
            "metrics": metrics}
    return ToolResult(status=status, data=data, ids=ids, source=source, warnings=warnings)


TOOL = Tool("get_financials", "Annual financials from SEC filings (10-K), newest fiscal year first, as known at the "
            "research cutoff: revenue, margins inputs, cash flow, capex, EPS, balance sheet and shares. Every value has "
            "a fact ID to cite and to pass to calculate.", GetFinancialsInput, run, "SEC companyfacts")
