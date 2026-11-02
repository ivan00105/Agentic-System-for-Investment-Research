"""Deterministic financial reports and bounded SEC company-facts retrieval."""

import json
import os
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo

import httpx
from pydantic import BaseModel, ConfigDict

from .contracts import Claim, CompanyReport, DomainError, Evidence, Metric, UNIVERSE, utcnow
from .store import Store
from .filings import fetch_source, retrieve_packet
from .financials import eligible_fact, operating_margin, parse_filing_facts


def metrics(revenue: Decimal | None, income: Decimal | None, period: str, evidence_ids: list[str]):
    margin = income / revenue if income is not None and revenue is not None and revenue > 0 else None
    return [
        Metric(id="revenue", label="Annual revenue", value=revenue, unit="USD", period=period, evidence_ids=evidence_ids, unavailable_reason="Comparable annual revenue is unavailable." if revenue is None else None),
        Metric(id="operating_income", label="Operating income", value=income, unit="USD", period=period, evidence_ids=evidence_ids, unavailable_reason="Comparable annual operating income is unavailable." if income is None else None),
        Metric(id="operating_margin", label="Operating margin", value=margin, unit="ratio", period=period, formula="operating_income / revenue", inputs=["operating_income", "revenue"], evidence_ids=evidence_ids, unavailable_reason="Requires matching annual income and positive revenue." if margin is None else None),
    ]


def company_report(ticker: str, values: list[Metric], limitations: list[str], *, facts=None, calculations=None):
    margin = next(m for m in values if m.id == "operating_margin")
    statement = f"Annual operating margin is {margin.value:.1%} for {margin.period}." if margin.value is not None else "Annual operating margin cannot be calculated from the available evidence."
    claims = [Claim(id=f"{ticker}-margin", statement=statement, kind="calculation", status="supported" if margin.value is not None else "unresolved", evidence_ids=margin.evidence_ids)]
    revenue = next(m for m in values if m.id == "revenue")
    if revenue.value is not None:
        claims.append(Claim(id=f"{ticker}-revenue", statement=f"Annual revenue is USD {revenue.value:,.0f} for {revenue.period}.", kind="fact", status="supported", evidence_ids=revenue.evidence_ids))
    return CompanyReport(ticker=ticker, company=UNIVERSE[ticker]["name"], summary=statement + " Inspect the aligned inputs and source before interpreting this result.", metrics=values, claims=claims, reviews=[], limitations=limitations.copy(), source_limitations=limitations.copy(), review_status="not_requested", facts=facts or [], calculations=calculations or [])


class SecFact(BaseModel):
    model_config = ConfigDict(extra="ignore", allow_inf_nan=False)
    start: date
    end: date
    val: Decimal
    accn: str
    filed: date
    form: str


def conservative_availability(filed: date):
    # A filing date is an Eastern calendar date. UTC midnight would admit some
    # late-evening Eastern filings before they were actually public.
    return datetime.combine(filed + timedelta(days=1), time.min, ZoneInfo("America/New_York")).astimezone(timezone.utc)


def eligible_facts(payload: dict, tag: str, cutoff: datetime):
    collection = payload
    for key in ("facts", "us-gaap", tag, "units"):
        collection = collection.get(key, {})
        if not isinstance(collection, dict):
            raise DomainError("SEC returned an invalid fact collection.", "source_format")
    units = collection.get("USD", [])
    if not isinstance(units, list):
        raise DomainError("SEC returned an invalid fact collection.", "source_format")
    facts = []
    for raw in units:
        try:
            fact = SecFact.model_validate(raw)
        except ValueError:
            continue
        available = conservative_availability(fact.filed)
        if fact.form in ("10-K", "10-K/A") and 330 <= (fact.end - fact.start).days <= 380 and available <= cutoff and fact.end <= fact.filed:
            facts.append(fact)
    return facts


def extract_annual(payload: dict, ticker: str, cutoff: datetime):
    if str(payload.get("cik", "")).zfill(10) != UNIVERSE[ticker]["cik"]:
        raise DomainError("Source issuer does not match the requested company.", "issuer_mismatch")
    # A company can change revenue tags; tag order must not select an older year.
    revenue = [
        (fact, tag)
        for tag in ("RevenueFromContractWithCustomerExcludingAssessedTax", "Revenues", "SalesRevenueNet")
        for fact in eligible_facts(payload, tag, cutoff)
    ]
    income = eligible_facts(payload, "OperatingIncomeLoss", cutoff)
    if not revenue:
        return None, None, None
    newest, tag = max(revenue, key=lambda item: (item[0].end, item[0].filed, item[0].accn))
    same_revenue = [r for r, _ in revenue if (r.start, r.end, r.accn) == (newest.start, newest.end, newest.accn)]
    if len({r.val for r in same_revenue}) != 1:
        raise DomainError("Conflicting revenue values require manual source review.", "ambiguous_fact")
    matching = [f for f in income if (f.start, f.end, f.accn) == (newest.start, newest.end, newest.accn)]
    if len({f.val for f in matching}) > 1:
        raise DomainError("Conflicting operating income values require manual source review.", "ambiguous_fact")
    return newest, matching[0] if matching else None, tag


def retrieve_company(store: Store, run_id: str, ticker: str, cutoff: datetime):
    user_agent = os.getenv("SEC_USER_AGENT", "").strip()
    if not user_agent or "@" not in user_agent:
        raise DomainError("New research needs SEC source access setup. Follow the setup guide, or open a saved report.", "configuration", 503)
    url = f"https://data.sec.gov/api/xbrl/companyfacts/CIK{UNIVERSE[ticker]['cik']}.json"
    try:
        with httpx.Client(timeout=httpx.Timeout(20, connect=5), follow_redirects=False) as client:
            raw, aggregate_at = fetch_source(client, url, user_agent)
        payload = json.loads(raw)
        if not isinstance(payload, dict):
            raise ValueError("Expected object")
    except (httpx.HTTPError, ValueError) as exc:
        raise DomainError("SEC retrieval failed or returned invalid data. Saved results remain available; retry explicitly later.", "retrieval_failed", 502) from exc
    digest = store.snapshot(raw)
    revenue, income, tag = extract_annual(payload, ticker, cutoff)
    limitations = ["This report covers annual financial figures in USD. It does not include news, events or price forecasts.", "Filing availability is dated conservatively to the day after filing in New York; an exact publication time is unavailable.", "These figures come from the SEC's current record. They may not reproduce exactly what investors could see at an earlier date."]
    if revenue is None:
        calculation = operating_margin(None, None)
        values = metrics(None, None, "Unavailable", [])
        values[2].calculation_id = calculation.id
        return company_report(ticker, values, limitations, calculations=[calculation])
    period = f"{revenue.start} – {revenue.end}"
    evidence_id = f"{ticker}-{revenue.accn}"
    excerpt = f"Issuer: {UNIVERSE[ticker]['name']} ({ticker})\nForm: {revenue.form}\nAccession: {revenue.accn}\nAnnual period: {period}\n{tag}: {revenue.val} USD\nOperatingIncomeLoss: {income.val if income else 'unavailable for matching accession and period'} USD\nFiled: {revenue.filed}"
    evidence = Evidence(id=evidence_id, ticker=ticker, title=f"{ticker} annual facts aggregate · {revenue.form}", excerpt=excerpt, source_url=url, available_at=conservative_availability(revenue.filed), retrieved_at=aggregate_at, period=period, locator=f"us-gaap/{tag} and us-gaap/OperatingIncomeLoss; accession {revenue.accn}", snapshot_hash=digest, source_kind="companyfacts")
    store.add_evidence(run_id, evidence)
    with httpx.Client(timeout=httpx.Timeout(20, connect=5), follow_redirects=False) as client:
        packet, document, filing_url, retrieved_at = retrieve_packet(store, ticker, revenue, cutoff, client, user_agent)
    filing_hash = packet.documents[-1].snapshot_hash
    filing_id = f"{ticker}-{revenue.accn}-filing-{filing_hash[:12]}"
    available_at = conservative_availability(packet.filed)
    checked_revenue, checked_income, table = parse_filing_facts(document, packet, revenue, filing_id, available_at, retrieved_at)
    if income is not None and checked_income is not None and income.val != checked_income.normalized_value:
        raise DomainError("Original operating income differs from the saved SEC company-facts selection.", "ambiguous_fact")
    from .contracts import SourceDocument
    table_raw, start, end = document.fragment(table)
    packet.documents.append(SourceDocument(role="table", source_url=filing_url, snapshot_hash=store.snapshot(table_raw),
                            byte_length=len(table_raw), media_type="text/html", retrieved_at=retrieved_at))
    original = Evidence(id=filing_id, ticker=ticker, title=f"{ticker} original annual filing table · {packet.form}",
        excerpt=table.text(), source_url=filing_url, available_at=available_at, retrieved_at=retrieved_at,
        period=period, locator=f"Original filing table bytes [{start},{end}); {checked_revenue.locator}",
        snapshot_hash=filing_hash, source_kind="filing_table", packet=packet)
    store.add_evidence(run_id, original)
    calculation = operating_margin(checked_revenue, checked_income)
    rev_value = checked_revenue.normalized_value if eligible_fact(checked_revenue) else None
    income_value = checked_income.normalized_value if checked_income is not None and eligible_fact(checked_income) else None
    values = metrics(rev_value, income_value, period, [filing_id])
    values[0].fact_id = checked_revenue.id if rev_value is not None else None
    values[1].fact_id = checked_income.id if income_value is not None else None
    values[2].value = calculation.result
    values[2].calculation_id = calculation.id
    values[2].unavailable_reason = f"Operating margin is unavailable: {calculation.failure}." if calculation.failure else None
    if calculation.failure:
        limitations.append(f"Original filing calculation unavailable: {calculation.failure}. Unknown basis or scope is not validated.")
    return company_report(ticker, values, limitations, facts=[f for f in (checked_revenue, checked_income) if f is not None], calculations=[calculation])
