"""A filing's own inline-XBRL facts in companyfacts' row shape, for an annual filing SEC companyfacts holds only the
cover of (TSMC's FY2025 20-F, REFERENCE §5). Whole-company facts only, as `ixbrl.facts` reads them; `sec_facts.select`
then applies the usual period, cutoff, unit and restatement rules."""
from . import ixbrl, sec_facts
from .cache import DiskCache
from .errors import DataError
from .sec import SecClient
from .sec_filings import Filing


def _units(payload: dict, tag: str) -> dict:
    taxonomy, name = tag.split(":")
    return payload.get("facts", {}).get(taxonomy, {}).get(name, {}).get("units", {})


def merged(payload: dict, sec: SecClient, filing: Filing, cache: DiskCache) -> tuple[dict, int]:
    """`payload` plus the filing's facts for each concept tag companyfacts has none of from that filing, and how many
    rows were added. `payload` itself is not changed."""
    if not filing.primary_document.lower().endswith((".htm", ".html")):
        raise DataError("The filing's main document is not HTML, so its inline XBRL can't be read.", "bad_data")
    tags = {tag for concept in (*sec_facts.CONCEPTS.values(), sec_facts.NCI) for tag in concept.tags}
    known = {tag for tag in tags if any(row.get("accn") == filing.accession
                                        for rows in _units(payload, tag).values() for row in rows)}
    facts = {taxonomy: dict(names) for taxonomy, names in payload.get("facts", {}).items()}
    copied, seen = set(), set()
    for fact in ixbrl.facts(sec, filing, cache):
        tag, unit = fact["concept"], fact["unit"]
        key = (tag, unit, fact["start"], fact["end"], fact["value"])
        if tag not in tags or tag in known or fact["value"] is None or not unit or not fact["end"] or key in seen:
            continue
        seen.add(key)
        taxonomy, name = tag.split(":")
        names = facts.setdefault(taxonomy, {})
        if tag not in copied:  # copy only what changes
            old = names.get(name, {})
            names[name] = {**old, "units": {u: list(rows) for u, rows in old.get("units", {}).items()}}
            copied.add(tag)
        names[name]["units"].setdefault(unit, []).append({
            "start": fact["start"], "end": fact["end"], "val": fact["value"], "accn": filing.accession,
            "form": filing.form, "filed": filing.filed.isoformat(), "document": filing.url, "locator": fact["locator"]})
    return {**payload, "facts": facts}, len(seen)
