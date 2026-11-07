"""verify_against_filing: check a get_financials fact against the number tagged in the original filing.

A critic tool: it reads the filing itself, not companyfacts, so it can disagree with get_financials.
"""
from decimal import Decimal

from pydantic import BaseModel, Field

from ..data import ixbrl, sec_filings
from .result import Tool, ToolContext, ToolResult, make_id


class VerifyInput(BaseModel):
    fact_id: str = Field(min_length=1, description="A fact ID returned by get_financials.")


def run(args: VerifyInput, context: ToolContext) -> ToolResult:
    source = "SEC filing (inline XBRL)"
    fact = context.records.get(args.fact_id)
    if fact is None or fact.get("kind") != "fact" or not fact.get("accession"):
        return ToolResult(status="invalid", source=source, warnings=[f"{args.fact_id} is not a fact ID from get_financials."])
    filing = sec_filings.find(context.sec, fact["cik"], fact["accession"])
    if filing is None:
        return ToolResult(status="not_found", source=source, warnings=[f"Filing {fact['accession']} is not in SEC's list."])
    if not filing.primary_document.lower().endswith((".htm", ".html")):
        return ToolResult(status="unsupported", source=source, warnings=["The filing's main document is not HTML."])
    found = ixbrl.facts(context.sec, filing, context.cache("ixbrl_cache"))
    if not found:
        return ToolResult(status="unsupported", source=source, warnings=[
            "The filing has no inline XBRL (SEC required it from 2019), so it can't be checked this way."])
    tagged = [f for f in found if f["concept"] == fact["tag"] and f["end"] == fact["end"]
              and (f["start"] or None) == fact["start"]]
    unit = fact.get("reported_unit") or fact["unit"]  # a converted figure is checked in the currency it was filed in
    same = [f for f in tagged if f["unit"] == unit]  # USD only ever checks against USD
    readable = [f for f in same if f["value"] is not None]
    # A count the page prints in full, or a profit less non-controlling interests, is checked against its tag's own
    # number; a converted figure against the filed value.
    expected = fact.get("tagged_value") or fact.get("reported_value") or fact["value"]
    matches = [f for f in readable if Decimal(f["value"]) == Decimal(expected)]
    # A number we can't read is "unverified", never a mismatch.
    verdict = "match" if matches else "mismatch" if readable else "unverified" if same else "not_in_filing"
    shown = (matches or readable or same or tagged)[:5]
    record = {"id": make_id("check", args.fact_id, filing.accession), "kind": "check", "fact_id": args.fact_id,
              "verdict": verdict, "expected": expected, "concept": fact["tag"], "period_end": fact["end"],
              "filing_url": filing.url, "found": shown}
    context.remember(record)
    warnings = []
    if fact.get("tagged_value") and matches:
        warnings.append(f"The fact uses {fact.get('reported_value') or fact['value']}, not the tag's {expected}; its "
                        "notes say why.")
    if verdict == "mismatch":
        warnings.append(f"The filing tags {fact['tag']} for this period as {', '.join(f['raw'] for f in shown)}, "
                        f"not {expected}.")
    elif verdict == "unverified":
        warnings.append(f"The filing tags {fact['tag']} for this period, but its number "
                        f"({', '.join(repr(f['raw']) + ' format ' + (f['format'] or 'none') for f in shown)}) could not "
                        "be read, so it was not checked.")
    elif tagged and not same:
        units = sorted({f["unit"] or "an unreadable unit" for f in tagged})
        warnings.append(f"{fact['tag']} for this period is tagged only in {', '.join(units)}, not {unit}.")
    elif verdict == "not_in_filing":
        warnings.append(f"{fact['tag']} for this period is not tagged in {filing.accession}; companyfacts may come "
                        "from a different filing or a dimensioned (segment) fact.")
    elif all(f["hidden"] for f in matches):
        warnings.append("The value is only in the filing's hidden XBRL, not in a visible table.")
    return ToolResult(status="ok", data=record, ids=[record["id"]], source=source, warnings=warnings)


TOOL = Tool("verify_against_filing", "Check a fact from get_financials against the number tagged in the original SEC "
            "filing (inline XBRL). Returns match, mismatch or not_in_filing, with the table row and byte location.",
            VerifyInput, run, "SEC filing (inline XBRL)")
