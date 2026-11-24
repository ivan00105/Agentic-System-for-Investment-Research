"""get_base_rates: SEC first-reported business-growth outside view."""
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, Field

from ..data import sec_facts
from ..data.sec import cik10
from ..finance import base_rates
from .result import Tool, ToolContext, ToolResult, make_id


class GetBaseRatesInput(BaseModel):
    cik: str = Field(pattern=r"^[0-9]{1,10}$", description="Target company's CIK.")
    comparable_ciks: list[str] = Field(default_factory=list,
                                       description="CIKs for the reference class, including dead or acquired filers.")
    revenue_floor: Decimal = Field(default=Decimal("100000000"), ge=0)
    growth_thresholds: list[Decimal] = Field(default_factory=lambda: [Decimal("0"), Decimal(".1")])


def _rows(payload: dict, concept: sec_facts.Concept, cutoff: datetime) -> list[dict]:
    result = []
    for tag in concept.tags:
        taxonomy, name = tag.split(":")
        for row in payload.get("facts", {}).get(taxonomy, {}).get(name, {}).get("units", {}).get(concept.unit, []):
            try:
                filed = row["filed"]
                if sec_facts.available_at(datetime.fromisoformat(filed).date()) > cutoff:
                    continue
                result.append({**row, "value": row["val"]})
            except (KeyError, TypeError, ValueError):
                continue
    return result


def run(args: GetBaseRatesInput, context: ToolContext) -> ToolResult:
    target = cik10(args.cik)
    ciks = list(dict.fromkeys([target, *(cik10(cik) for cik in args.comparable_ciks)]))
    samples = []
    warnings = []
    for cik in ciks:
        try:
            payload = context.sec.companyfacts(cik).json()
        except Exception as exc:
            warnings.append(f"{cik} was not available and is absent from the sample ({exc}).")
            continue
        revenue = _rows(payload, sec_facts.CONCEPTS["revenue"], context.cutoff)
        operating = _rows(payload, sec_facts.CONCEPTS["operating_income"], context.cutoff)
        years = base_rates.observations(cik, revenue, operating, args.revenue_floor,
                                        context.cutoff.date().isoformat())
        samples.extend(base_rates.next_year_changes(years))
    data = base_rates.forecast(samples, args.growth_thresholds)
    if len(ciks) == 1:
        warnings.insert(0, "No comparable companies were passed, so this is the company's own history, not an outside "
                        "view.")
    data.update({"target_cik": target, "reference_class_size": len(ciks), "revenue_floor": str(args.revenue_floor),
                 "first_reported": True,
                 "sample": "the companies passed in" if len(ciks) > 1 else "the company's own history"})
    record = {"id": make_id("base-rates", target, *(sorted(ciks)), context.cutoff.isoformat()),
              "kind": "calc", "formula": "base_rates", "cik": target, "value": None, "unit": "distribution",
              "status": "ok" if samples else "unavailable", "data": data,
              "notes": ["Each fiscal year uses its earliest filed full-year value; later restatements are excluded.",
                        "The sample is only the CIKs passed in, so it leans to survivors unless dead and acquired "
                        "filers are among them."]}
    context.remember(record)
    return ToolResult(status=record["status"], data=data, ids=[record["id"]], source="SEC companyfacts (first-reported)",
                      warnings=warnings + ([] if samples else ["No comparable annual pairs were available."]))


TOOL = Tool("get_base_rates", "Build an outside-view distribution of next-year revenue growth and operating-margin "
            "change from first-reported SEC annual values. Include dead or acquired CIKs in comparable_ciks.",
            GetBaseRatesInput, run, "SEC companyfacts")
