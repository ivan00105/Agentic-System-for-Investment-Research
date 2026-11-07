"""get_financials: multi-year annual fundamentals from SEC companyfacts, each value citable by ID. A newest annual
filing companyfacts holds only the cover of is read from its own inline XBRL instead (REFERENCE §5)."""
from functools import partial
from typing import Literal

from pydantic import BaseModel, Field

from .. import config
from ..data import companies, filing_facts, sec_facts, sec_filings
from ..data.sec import cik10
from ..data.errors import DataError
from . import fx_convert, share_basis
from .result import Tool, ToolContext, ToolResult, make_id

Metric = Literal[tuple(sec_facts.CONCEPTS)]
NOT_REPORTED_BY_FINANCIALS = {"operating_income", "gross_profit"}


class GetFinancialsInput(BaseModel):
    cik: str = Field(pattern=r"^[0-9]{1,10}$", description="The company's CIK from find_company.")
    metrics: list[Metric] | None = Field(None, description="Metrics to return; omit for all of them.")
    years: int | None = Field(None, ge=1, description=f"Most recent fiscal years to return (default "
                              f"{config.FINANCIALS_DEFAULT_YEARS}); older years are counted in a warning.")


def _pick(payload: dict, context: ToolContext, cik: str, url: str, year_ends: set, oldest, years: int, concept,
          unit: str) -> tuple[list, list[dict], list[str]]:
    """Every fact in `unit` before the cutoff, the records of those shown (the newest `years`), and select's warnings."""
    facts, problems = sec_facts.select(payload, concept, context.cutoff, year_ends, unit)
    shown = [f for f in facts if oldest is not None and f.end >= oldest]
    if concept.kind != "cover":
        shown = shown[:years]
    return facts, [_record(cik, concept.metric, f, url) for f in shown], problems


def _record(cik: str, name: str, fact, url: str) -> dict:
    record = {"id": make_id("fact", cik, fact.tag, fact.start, fact.end, fact.accession, fact.value), "kind": "fact",
              "cik": cik, "metric": name, "tag": fact.tag, "unit": fact.unit, "value": str(fact.value),
              "start": fact.start and fact.start.isoformat(), "end": fact.end.isoformat(),
              "accession": fact.accession, "form": fact.form, "filed": fact.filed.isoformat(),
              "available_at": sec_facts.available_at(fact.filed).isoformat(), "source_url": url,
              "filing_url": f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{fact.accession.replace('-', '')}/"}
    if fact.original_value is not None:
        record.update(original_value=str(fact.original_value), original_accession=fact.original_accession)
    if fact.document:
        record.update(source_url=fact.document, locator=fact.locator, notes=[
            "Read from the filing's own inline XBRL: SEC companyfacts has only this filing's cover."])
    if fact.tagged_value is not None:  # verify_against_filing checks the tag's own number
        record.update(tagged_value=str(fact.tagged_value), notes=[*record.get("notes", []), fact.note])
    return record


def _fill_unread(context: ToolContext, cik: str, payload: dict) -> tuple[dict, str | None]:
    """When companyfacts holds only the newest annual filing's cover (TSMC's FY2025 20-F), that filing's own inline
    XBRL facts are added; plus a warning saying which happened."""
    unread = sec_facts.unread_annual_filing(payload, context.cutoff)
    if unread is None:
        return payload, None
    lacks = (f"The newest {unread.form} ({unread.accession}, filed {unread.filed}) has only its cover in SEC "
             "companyfacts, none of its statements")
    try:
        filing = sec_filings.find(context.sec, cik, unread.accession)
        if filing is None:
            raise DataError(f"filing {unread.accession} is not in SEC's list", "not_found")
        filled, added = filing_facts.merged(payload, context.sec, filing, context.cache("ixbrl_cache"))
    except DataError as exc:
        return payload, f"{lacks}, and reading the filing itself failed ({exc}), so its figures are missing here."
    if not added:
        return payload, f"{lacks}, and its inline XBRL has none of these figures either."
    return filled, (f"{lacks}, so its figures here are read from the filing's own inline XBRL ({filing.url}); each such "
                    "value's notes say so.")


def run(args: GetFinancialsInput, context: ToolContext) -> ToolResult:
    cik = cik10(args.cik)
    response = context.sec.companyfacts(cik)
    payload = response.json()
    source = "SEC companyfacts"
    if not sec_facts.taxonomies(payload) & {"us-gaap", "ifrs-full"}:
        return ToolResult(status="unsupported", source=source, data={"cik": cik, "name": payload.get("entityName")},
                          warnings=[f"{payload.get('entityName', cik)} reports no US GAAP or IFRS financial statements "
                                    "in companyfacts."])
    years = args.years or config.FINANCIALS_DEFAULT_YEARS
    metrics, ids, warnings, converted, rates = {}, [], [], {}, []
    if sec_facts.fiscal_year_ends(payload, context.cutoff):
        filled, note = _fill_unread(context, cik, payload)
        if filled is not payload:
            payload, source = filled, source + "; SEC filing (inline XBRL)"
        warnings += [note] if note else []
    year_ends = sec_facts.fiscal_year_ends(payload, context.cutoff)
    kept_ends = sorted(year_ends, reverse=True)[:years]
    oldest = min(kept_ends) if kept_ends else None
    financial = None  # looked up only if a metric is missing
    pick = partial(_pick, payload, context, cik, response.url, year_ends, oldest, years)
    for name in args.metrics or list(sec_facts.CONCEPTS):
        concept = sec_facts.CONCEPTS[name]
        used = sec_facts.reporting_unit(payload, concept, context.cutoff)
        facts, records, problems = pick(concept, used)
        if used != concept.unit and records:
            try:
                pairs = [fx_convert.to_usd(context, r) for r in records]
                records, converted[name] = [r for r, _ in pairs], used[:3]
                rates += [rate for _, rate in pairs]
            except DataError as exc:  # no rate: the filing's own USD figures, if it has any
                facts, records, problems = pick(concept, concept.unit)
                if not records:
                    metrics[name] = {"status": "unsupported", "reason": f"Reported in {used}, not {concept.unit}, "
                                     f"and no exchange rate is available: {exc}"}
                    continue
                warnings.append(f"{name}: no {used} exchange rate ({exc}), so the filing's own {concept.unit} "
                                "figures are shown.")
                used = concept.unit
        warnings += problems
        if len(facts) > len(records):
            warnings.append(f"{name}: {len(facts) - len(records)} older values not shown; ask for more years to see them.")
        if not records:
            if not {t.split(":")[0] for t in concept.tags} & (filed_in := sec_facts.taxonomies(payload) - {"dei", "srt"}):
                metrics[name] = {"status": "unsupported", "reason": f"This filer reports under {', '.join(sorted(filed_in))}"
                                 f", and {name} is read only from {', '.join(concept.tags)}."}
                continue
            if financial is None:
                financial = companies.profile(context.sec, cik)["financial_sector"]
            unsupported = financial and name in NOT_REPORTED_BY_FINANCIALS
            metrics[name] = {"status": "unsupported" if unsupported else "not_reported", "reason": (
                "Banks, brokers and insurers don't report this line." if unsupported else
                f"No annual value before the cutoff under {', '.join(concept.tags)}.")}
            continue
        values = []
        for record in records:
            if record.get("original_value") is not None:
                warnings.append(f"{name} for the period ending {record['end']} was restated: first reported as "
                                f"{record['original_value']} in {record['original_accession']}, now "
                                f"{record.get('reported_value', record['value'])}.")
            ids.append(context.remember(record))
            values.append({k: v for k, v in record.items() if k not in ("kind", "cik", "metric", "unit", "source_url")})
        metrics[name] = {"status": "ok", "unit": concept.unit, "values": values}
        if (units := sec_facts.other_units(payload, concept, context.cutoff)) and used == concept.unit == "USD":
            warnings.append(f"{name} is also reported in {', '.join(units)}: the USD figures are probably convenience "
                            "translations at one exchange rate per filing, so changes across years mix exchange rates.")
    if converted:
        sources = sorted({rate.source for rate in rates})
        source += f"; exchange rates: {', '.join(sources)}"
        warnings.append(f"Converted to USD from {', '.join(sorted(set(converted.values())))} at {', '.join(sources)} "
                        f"rates (each year's average for income and cash flow, the year-end rate for balances): "
                        f"{', '.join(converted)}. Changes across years include exchange-rate moves; the filing's own USD "
                        "figures, if any, are convenience translations at one rate and are not used.")
        warnings += list(dict.fromkeys(note for rate in rates for note in rate.notes))
    share_basis.add(context, cik, metrics, ids, warnings)
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


TOOL = Tool("get_financials", "Annual financials from SEC filings (10-K, 20-F, 40-F; US GAAP or IFRS), newest fiscal "
            "year first, as known at the research cutoff: revenue, margins inputs, cash flow, capex, EPS, balance sheet "
            "and shares. Every value has a fact ID to cite and to pass to calculate. Figures a foreign filer reports in another currency come converted "
            "to USD, each with its filed value, rate and rate source. A 20-F/40-F share count comes with ordinary_shares_per_ads from the "
            "same filing (calculate's ads_ratio for market cap).", GetFinancialsInput, run, "SEC companyfacts")
