"""Annual facts from SEC companyfacts, chosen by tag, period and filing date as of a cutoff (REFERENCE §5).

Never "the last value in the array" and never the `fy` field: a period is identified by its start and
end dates, and a value only counts once its filing was public before the cutoff.
"""
import re
from dataclasses import dataclass, replace
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal, InvalidOperation
from zoneinfo import ZoneInfo

# Foreign private issuers that report US GAAP (e.g. Chinese ADRs) file their annual report as a 20-F or 40-F.
ANNUAL_FORMS = {"10-K", "10-K/A", "20-F", "20-F/A", "40-F", "40-F/A"}
COVER_FORMS = ANNUAL_FORMS | {"10-Q", "10-Q/A"}
NEW_YORK = ZoneInfo("America/New_York")


@dataclass(frozen=True)
class Concept:
    metric: str
    tags: tuple[str, ...]  # "taxonomy:Name", best first; each period uses the best tag its filing reported
    unit: str
    kind: str  # duration: a fiscal year; instant: a fiscal year end; cover: any 10-K/10-Q cover date


# IFRS filers (TSMC) come last: edgartools 5.62.1's names (https://github.com/dgunning/edgartools), from
# edgar/standardization/synonym_groups.py and edgar/entity/mappings_loader.py. Owners' lines match US GAAP's parent's.
CONCEPTS = {c.metric: c for c in (
    Concept("revenue", ("us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax", "us-gaap:Revenues",
                        "us-gaap:SalesRevenueNet", "us-gaap:RevenueFromContractWithCustomerIncludingAssessedTax",
                        "us-gaap:RevenuesNetOfInterestExpense", "ifrs-full:Revenue",
                        "ifrs-full:RevenueFromContractsWithCustomers"), "USD", "duration"),
    Concept("gross_profit", ("us-gaap:GrossProfit", "ifrs-full:GrossProfit"), "USD", "duration"),
    Concept("operating_income", ("us-gaap:OperatingIncomeLoss", "ifrs-full:ProfitLossFromOperatingActivities"),
            "USD", "duration"),
    Concept("net_income", ("us-gaap:NetIncomeLoss", "ifrs-full:ProfitLossAttributableToOwnersOfParent",
                           "ifrs-full:ProfitLoss"), "USD", "duration"),
    Concept("research_and_development", ("us-gaap:ResearchAndDevelopmentExpense",
             "us-gaap:ResearchAndDevelopmentExpenseExcludingAcquiredInProcessCost",
             "ifrs-full:ResearchAndDevelopmentExpense"), "USD", "duration"),
    Concept("operating_cash_flow", ("us-gaap:NetCashProvidedByUsedInOperatingActivities",
             "us-gaap:NetCashProvidedByUsedInOperatingActivitiesContinuingOperations",
             "ifrs-full:CashFlowsFromUsedInOperatingActivities"), "USD", "duration"),
    # Payments, so a positive number is cash spent.
    Concept("capex", ("us-gaap:PaymentsToAcquirePropertyPlantAndEquipment",
                      "us-gaap:PaymentsToAcquireProductiveAssets",
                      "ifrs-full:PurchaseOfPropertyPlantAndEquipmentClassifiedAsInvestingActivities"), "USD", "duration"),
    Concept("eps_diluted", ("us-gaap:EarningsPerShareDiluted", "ifrs-full:DilutedEarningsLossPerShare"),
            "USD/shares", "duration"),
    Concept("diluted_shares", ("us-gaap:WeightedAverageNumberOfDilutedSharesOutstanding",
                               "ifrs-full:AdjustedWeightedAverageShares"), "shares", "duration"),
    Concept("total_assets", ("us-gaap:Assets", "ifrs-full:Assets"), "USD", "instant"),
    Concept("total_liabilities", ("us-gaap:Liabilities", "ifrs-full:Liabilities"), "USD", "instant"),
    Concept("stockholders_equity", ("us-gaap:StockholdersEquity", "ifrs-full:EquityAttributableToOwnersOfParent"),
            "USD", "instant"),
    Concept("cash", ("us-gaap:CashAndCashEquivalentsAtCarryingValue", "ifrs-full:CashAndCashEquivalents"), "USD",
            "instant"),
    # Total long-term debt first; the noncurrent part only when the total isn't tagged. Never summed. No IFRS tag:
    # IFRS has no total, and TSMC's LongtermBorrowings (bank loans) leaves out its bonds, about 30 times larger.
    Concept("long_term_debt", ("us-gaap:LongTermDebt", "us-gaap:LongTermDebtNoncurrent"), "USD", "instant"),
    # Cover-page count first. Issuers with several share classes only tag it per class, which companyfacts
    # drops, so the balance-sheet total is the fallback.
    Concept("shares_outstanding", ("dei:EntityCommonStockSharesOutstanding",
                                   "us-gaap:CommonStockSharesOutstanding"), "shares", "cover"),
)}
FISCAL_YEAR_METRICS = ("revenue", "net_income", "operating_cash_flow")
# ASC 606 / IFRS 15 contract revenue leaves out lease income (REITs) and interest (banks), so it can be a slice of the
# total. TSMC's FY2025 20-F tags its NET REVENUE line only with the IFRS 15 tag.
CONTRACT_REVENUE_TAGS = ("us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax",
                         "us-gaap:RevenueFromContractWithCustomerIncludingAssessedTax",
                         "ifrs-full:RevenueFromContractsWithCustomers")
# IFRS ProfitLoss includes non-controlling interests, so net income is it less their share from the same filing.
PROFIT_LOSS_TAG = "ifrs-full:ProfitLoss"
NCI = Concept("net_income", ("ifrs-full:ProfitLossAttributableToNoncontrollingInterests",), "USD", "duration")


@dataclass(frozen=True)
class Fact:
    metric: str
    tag: str
    unit: str
    value: Decimal
    start: date | None
    end: date
    accession: str
    form: str
    filed: date
    original_value: Decimal | None = None  # set when an earlier filing reported a different value
    original_accession: str | None = None
    document: str | None = None  # set when read from the filing's own inline XBRL, not companyfacts
    locator: str | None = None
    tagged_value: Decimal | None = None  # set when `value` is derived from the tag's number
    note: str | None = None


def available_at(filed: date) -> datetime:
    """SEC dates filings in New York; count one as public from the next New York midnight."""
    return datetime.combine(filed + timedelta(days=1), time.min, NEW_YORK).astimezone(timezone.utc)


def taxonomies(payload: dict) -> set[str]:
    return set(payload.get("facts", {}))


def _rows(payload: dict, concept: Concept, cutoff: datetime, unit: str | None = None):
    for priority, tag in enumerate(concept.tags):
        taxonomy, name = tag.split(":")
        rows = payload.get("facts", {}).get(taxonomy, {}).get(name, {}).get("units", {}).get(unit or concept.unit, [])
        for row in rows:
            try:
                end, filed = date.fromisoformat(row["end"]), date.fromisoformat(row["filed"])
                start = date.fromisoformat(row["start"]) if row.get("start") else None
                value, accession, form = Decimal(str(row["val"])), str(row["accn"]), str(row["form"])
            except (KeyError, TypeError, ValueError, InvalidOperation):
                continue  # one malformed row must not hide the others
            if available_at(filed) > cutoff or end > filed:
                continue
            if concept.kind == "duration" and not (form in ANNUAL_FORMS and start and 330 <= (end - start).days <= 380):
                continue
            if concept.kind == "instant" and form not in ANNUAL_FORMS:
                continue
            if concept.kind == "cover" and form not in COVER_FORMS:
                continue
            yield priority, tag, Fact(concept.metric, tag, unit or concept.unit, value, start, end, accession, form, filed,
                                      document=row.get("document"), locator=row.get("locator"))


def other_units(payload: dict, concept: Concept, cutoff: datetime) -> list[str]:
    """Units the concept's annual rows public at the cutoff are in besides the one we support, e.g. ["CNY"] for a
    Chinese ADR."""
    found = set()
    for tag in concept.tags:
        taxonomy, name = tag.split(":")
        found |= set(payload.get("facts", {}).get(taxonomy, {}).get(name, {}).get("units", {}))
    return sorted(u for u in found - {concept.unit} if next(_rows(payload, concept, cutoff, u), None))


def reporting_unit(payload: dict, concept: Concept, cutoff: datetime) -> str:
    """The currency of most of a money concept's annual rows in the newest annual filing public at the cutoff. A
    foreign filer reporting in CNY tags three years in CNY per 20-F and only the latest in USD (a convenience
    translation), so CNY wins; ties keep USD. Older filings don't count, so a change of currency keeps the newest year."""
    if concept.unit not in ("USD", "USD/shares"):
        return concept.unit
    shape = re.compile(r"[A-Z]{3}" + concept.unit[3:])  # "CNY" or "CNY/shares"
    units = {unit for tag in concept.tags for unit in payload.get("facts", {}).get(tag.split(":")[0], {})
             .get(tag.split(":")[1], {}).get("units", {}) if shape.fullmatch(unit)}
    rows = [(unit, fact) for unit in units for _, _, fact in _rows(payload, concept, cutoff, unit)]
    if not rows:
        return concept.unit
    newest = max((fact.filed, fact.accession) for _, fact in rows)
    counts: dict[str, int] = {}
    for unit, fact in rows:
        if (fact.filed, fact.accession) == newest:
            counts[unit] = counts.get(unit, 0) + 1
    return max(counts, key=lambda u: (counts[u], u == concept.unit))


def unread_annual_filing(payload: dict, cutoff: datetime) -> Fact | None:
    """The newest annual cover count whose filing gave companyfacts no revenue, net income or cash flow (TSMC's FY2025
    20-F: its cover is there, its IFRS statements are not), else None. Amendments often carry only a cover, so skip them."""
    covers = [f for _, _, f in _rows(payload, CONCEPTS["shares_outstanding"], cutoff)
              if f.form in ANNUAL_FORMS and not f.form.endswith("/A")]
    if not covers:
        return None
    newest = max(covers, key=lambda f: (f.filed, f.accession))
    used = {str(row.get("accn")) for metric in FISCAL_YEAR_METRICS for tag in CONCEPTS[metric].tags
            for rows in payload.get("facts", {}).get(tag.split(":")[0], {}).get(tag.split(":")[1], {})
            .get("units", {}).values() for row in rows}
    return None if newest.accession in used else newest


def fiscal_year_ends(payload: dict, cutoff: datetime) -> set[date]:
    return {f.end for metric in FISCAL_YEAR_METRICS
            for _, _, f in _rows(payload, CONCEPTS[metric], cutoff, reporting_unit(payload, CONCEPTS[metric], cutoff))}


def select(payload: dict, concept: Concept, cutoff: datetime, year_ends: set[date],
           unit: str | None = None) -> tuple[list[Fact], list[str]]:
    """One fact per period in `unit` (default: the concept's), newest period first, plus warnings about conflicts."""
    periods: dict[tuple, list] = {}
    for priority, tag, fact in _rows(payload, concept, cutoff, unit):
        if concept.kind == "instant" and fact.end not in year_ends:
            continue
        periods.setdefault((fact.start, fact.end), []).append((priority, tag, fact))
    chosen, warnings = [], []
    for (_, end), candidates in sorted(periods.items(), key=lambda item: item[0][1], reverse=True):
        # The latest filing before the cutoff is the best knowledge of that period; within it, the best tag,
        # except that a larger total replaces contract revenue. Restatements compare values under that tag only.
        latest = max(f.filed for _, _, f in candidates)
        accession = max(f.accession for _, _, f in candidates if f.filed == latest)
        in_filing = [(p, f) for p, _, f in candidates if f.accession == accession]
        tag = concept.tags[min(p for p, _ in in_filing)]
        if tag in CONTRACT_REVENUE_TAGS:
            tag = _total_tag([f for _, f in in_filing], tag)
        same = [f for _, f in in_filing if f.tag == tag]
        if len({f.value for f in same}) > 1:
            warnings.append(f"{concept.metric} for the period ending {end} has conflicting values in filing "
                            f"{accession}; withheld until checked by hand.")
            continue
        fact = same[0]
        if fact.tag == PROFIT_LOSS_TAG and (fact := _owners_share(payload, cutoff, fact)) is None:
            warnings.append(f"{concept.metric} for the period ending {end}: filing {accession} tags only "
                            f"{PROFIT_LOSS_TAG}, which includes non-controlling interests, and not their share "
                            f"({NCI.tags[0]}), so the owners' profit can't be told; withheld.")
            continue
        if fact.tag in CONTRACT_REVENUE_TAGS and (older := [f for _, t, f in candidates if t not in CONTRACT_REVENUE_TAGS
                                                            and f.accession != accession and f.value > fact.value]):
            o = max(older, key=lambda f: f.filed)
            warnings.append(f"{concept.metric} for the period ending {end}: a larger {o.tag} total ({o.value}) is in "
                            f"filing {o.accession}, not the latest {accession}; the latest filing's value is kept.")
        earlier = sorted((f for _, t, f in candidates if t == fact.tag and f.filed < fact.filed), key=lambda f: f.filed)
        if earlier and fact.tag == PROFIT_LOSS_TAG:  # compare owners' profit with owners' profit
            earlier = [f for f in [_owners_share(payload, cutoff, earlier[0])] if f]
        if earlier and earlier[0].value != fact.value:
            fact = replace(fact, original_value=earlier[0].value, original_accession=earlier[0].accession)
        chosen.append(fact)
    return chosen, warnings


def _owners_share(payload: dict, cutoff: datetime, fact: Fact) -> Fact | None:
    """IFRS ProfitLoss less the non-controlling share the same filing tags for the same period, else None."""
    shares = {f.value for _, _, f in _rows(payload, NCI, cutoff, fact.unit)
              if (f.accession, f.start, f.end) == (fact.accession, fact.start, fact.end)}
    if len(shares) != 1:
        return None
    (other,) = shares
    return replace(fact, value=fact.value - other, tagged_value=fact.value, note=(
        f"Owners' profit: {PROFIT_LOSS_TAG} ({fact.value}) includes non-controlling interests, so their share in the "
        f"same filing ({other}, {NCI.tags[0]}) is subtracted."))


def _total_tag(facts: list[Fact], tag: str) -> str:
    """As in `_broadest`: the largest non-contract total above contract revenue, in one filing and period, wins."""
    floor = max(f.value for f in facts if f.tag == tag)
    totals = [f for f in facts if f.tag not in CONTRACT_REVENUE_TAGS and f.value > floor]
    return max(totals, key=lambda f: f.value).tag if totals else tag


def frame(sec, concept: Concept, year: int) -> dict[str, dict]:
    """Calendar-year values for every filer from SEC frames: {cik: {value, tag, accession, end, name}}.

    Frames hold each company's latest-filed value (restated, not point-in-time) for the fiscal period
    closest to the calendar year, so callers must say so and verify shortlisted names with companyfacts.
    A company keeps its best tag's value, except that a larger total for the same period replaces contract revenue.
    """
    from .errors import DataError
    from .sec import cik10

    hits: dict[str, list[dict]] = {}
    # US GAAP tags only, best first: an IFRS filer's USD frame holds just its convenience translations at one rate,
    # and each extra tag is another large download.
    for tag in (t for t in concept.tags if t.startswith("us-gaap:")):
        taxonomy, name = tag.split(":")
        period = f"CY{year}" if concept.kind == "duration" else f"CY{year}Q4I"
        try:
            rows = sec.get(f"https://data.sec.gov/api/xbrl/frames/{taxonomy}/{name}/{concept.unit}/{period}.json").json()["data"]
        except DataError as exc:
            if exc.code == "not_found":
                continue  # no filer used this tag for that year
            raise
        for row in rows:
            hits.setdefault(cik10(row["cik"]), []).append({
                "value": Decimal(str(row["val"])), "tag": tag, "accession": row.get("accn"), "end": row.get("end"),
                "name": row.get("entityName")})
    return {cik: _broadest(found) for cik, found in hits.items()}


def _broadest(found: list[dict]) -> dict:
    """A larger total replaces contract revenue only from the same filing; one from another filing is noted."""
    best = found[0]
    if best["tag"] not in CONTRACT_REVENUE_TAGS:
        return best
    totals = [f for f in found if f["tag"] not in CONTRACT_REVENUE_TAGS and f["end"] == best["end"]
              and f["value"] > best["value"]]
    if same := [f for f in totals if f["accession"] == best["accession"]]:
        return max(same, key=lambda f: f["value"])
    if totals:
        o = max(totals, key=lambda f: f["value"])
        return best | {"note": f"a larger {o['tag']} total ({o['value']}) is in filing {o['accession']}, not "
                               f"{best['accession']}; the {best['tag']} value is kept."}
    return best
