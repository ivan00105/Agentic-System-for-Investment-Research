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


def metrics(revenue: Decimal | None, income: Decimal | None, period: str, evidence_ids: list[str]):
    margin = income / revenue if income is not None and revenue is not None and revenue > 0 else None
    return [
        Metric(id="revenue", label="Annual revenue", value=revenue, unit="USD", period=period, evidence_ids=evidence_ids, unavailable_reason="Comparable annual revenue is unavailable." if revenue is None else None),
        Metric(id="operating_income", label="Operating income", value=income, unit="USD", period=period, evidence_ids=evidence_ids, unavailable_reason="Comparable annual operating income is unavailable." if income is None else None),
        Metric(id="operating_margin", label="Operating margin", value=margin, unit="ratio", period=period, formula="operating_income / revenue", inputs=["operating_income", "revenue"], evidence_ids=evidence_ids, unavailable_reason="Requires matching annual income and positive revenue." if margin is None else None),
    ]


def company_report(ticker: str, values: list[Metric], limitations: list[str]):
    margin = next(m for m in values if m.id == "operating_margin")
    statement = f"Annual operating margin is {margin.value:.1%} for {margin.period}." if margin.value is not None else "Annual operating margin cannot be calculated from the available evidence."
    claims = [Claim(id=f"{ticker}-margin", statement=statement, kind="calculation", status="supported" if margin.value is not None else "unresolved", evidence_ids=margin.evidence_ids)]
    revenue = next(m for m in values if m.id == "revenue")
    if revenue.value is not None:
        claims.append(Claim(id=f"{ticker}-revenue", statement=f"Annual revenue is USD {revenue.value:,.0f} for {revenue.period}.", kind="fact", status="supported", evidence_ids=revenue.evidence_ids))
    return CompanyReport(ticker=ticker, company=UNIVERSE[ticker]["name"], summary=statement + " Inspect the aligned inputs and source before interpreting this result.", metrics=values, claims=claims, reviews=[], limitations=limitations)


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
    units = payload.get("facts", {}).get("us-gaap", {}).get(tag, {}).get("units", {}).get("USD", [])
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
    revenue = []
    for tag in ("RevenueFromContractWithCustomerExcludingAssessedTax", "Revenues", "SalesRevenueNet"):
        revenue = eligible_facts(payload, tag, cutoff)
        if revenue:
            break
    income = eligible_facts(payload, "OperatingIncomeLoss", cutoff)
    if not revenue:
        return None, None, None
    newest = max(revenue, key=lambda f: (f.end, f.filed, f.accn))
    same_revenue = [r for r in revenue if (r.start, r.end, r.accn) == (newest.start, newest.end, newest.accn)]
    if len({r.val for r in same_revenue}) != 1:
        raise DomainError("Conflicting revenue values require manual source review.", "ambiguous_fact")
    matching = [f for f in income if (f.start, f.end, f.accn) == (newest.start, newest.end, newest.accn)]
    if len({f.val for f in matching}) > 1:
        raise DomainError("Conflicting operating income values require manual source review.", "ambiguous_fact")
    return newest, matching[0] if matching else None, tag


def retrieve_company(store: Store, run_id: str, ticker: str, cutoff: datetime):
    user_agent = os.getenv("SEC_USER_AGENT", "").strip()
    if not user_agent or "@" not in user_agent:
        raise DomainError("Fresh retrieval needs SEC_USER_AGENT with your application name and contact email. Set it on the server, or open a labelled saved replay.", "configuration", 503)
    url = f"https://data.sec.gov/api/xbrl/companyfacts/CIK{UNIVERSE[ticker]['cik']}.json"
    try:
        with httpx.Client(timeout=httpx.Timeout(20, connect=5), follow_redirects=False) as client:
            with client.stream("GET", url, headers={"User-Agent": user_agent, "Accept": "application/json"}) as response:
                response.raise_for_status()
                chunks, size = [], 0
                for chunk in response.iter_bytes():
                    size += len(chunk)
                    if size > 25_000_000:
                        raise DomainError("SEC response exceeds the local retrieval limit.", "source_limit")
                    chunks.append(chunk)
        raw = b"".join(chunks)
        payload = json.loads(raw)
        if not isinstance(payload, dict):
            raise ValueError("Expected object")
    except (httpx.HTTPError, ValueError) as exc:
        raise DomainError("SEC retrieval failed or returned invalid data. Saved results remain available; retry explicitly later.", "retrieval_failed", 502) from exc
    digest = store.snapshot(raw)
    revenue, income, tag = extract_annual(payload, ticker, cutoff)
    limitations = ["Annual USD company-facts only; events, news and price-based forecasting are not yet connected.", "SEC fact availability uses midnight following the filing date in America/New_York, converted to UTC; this endpoint does not supply an acceptance timestamp.", "The current SEC aggregate is not a historical vintage archive; cutoff filtering alone does not establish a leakage-free historical backtest."]
    if revenue is None:
        return company_report(ticker, metrics(None, None, "Unavailable", []), limitations)
    period = f"{revenue.start} – {revenue.end}"
    evidence_id = f"{ticker}-{revenue.accn}"
    excerpt = f"Issuer: {UNIVERSE[ticker]['name']} ({ticker})\nForm: {revenue.form}\nAccession: {revenue.accn}\nAnnual period: {period}\n{tag}: {revenue.val} USD\nOperatingIncomeLoss: {income.val if income else 'unavailable for matching accession and period'} USD\nFiled: {revenue.filed}"
    evidence = Evidence(id=evidence_id, ticker=ticker, title=f"{ticker} annual facts · {revenue.form}", excerpt=excerpt, source_url=url, available_at=conservative_availability(revenue.filed), retrieved_at=utcnow(), period=period, locator=f"us-gaap/{tag} and us-gaap/OperatingIncomeLoss; accession {revenue.accn}", snapshot_hash=digest)
    store.add_evidence(run_id, evidence)
    return company_report(ticker, metrics(revenue.val, income.val if income else None, period, [evidence_id]), limitations)
