"""Numeric inline-XBRL facts from an original filing, with byte offsets as provenance (REFERENCE §10).

Uses the old pipeline's `Document` parser, which keeps exact source positions. Only facts without
dimensions (whole-company values) are kept, and only the number formats SEC filings commonly use.
"""
import json
import re
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

from ..contracts import DomainError
from ..filings import Document
from .cache import DiskCache
from .errors import DataError
from .sec import SecClient
from .sec_filings import Filing

ZERO_FORMATS = {"fixed-zero", "zerodash", "zero-dash"}
NUMBER_FORMATS = {"", "num-dot-decimal", "numdotdecimal"} | ZERO_FORMATS
DIMENSIONS = {"segment", "scenario", "explicitmember", "typedmember"}


def _local(tag: str) -> str:
    return tag.split(":")[-1]


def _number(node) -> Decimal | None:
    text = node.text()
    form = _local(node.attrs.get("format", ""))
    if form not in NUMBER_FORMATS:
        return None
    if form in ZERO_FORMATS or text in {"-", "—", "–"}:
        return Decimal(0)
    digits = text.replace(",", "").strip()
    if not re.fullmatch(r"\d+(?:\.\d+)?", digits):
        return None
    try:
        scale = int(node.attrs.get("scale", "0"))
        value = Decimal(digits).scaleb(scale)
    except (ValueError, InvalidOperation):
        return None
    return -value if node.attrs.get("sign") == "-" else value


def _unit(node) -> str | None:
    """A unit in companyfacts' spelling: "USD", "CNY", "shares" or "USD/shares"; None if it can't be read."""
    if node is None:
        return None

    def measures(part):
        return [n.text().split(":")[-1] for n in part.nodes() if _local(n.tag) == "measure"]
    divide = next((n for n in node.nodes() if _local(n.tag) == "divide"), None)
    if divide is None:
        found = measures(node)
        return found[0] if len(found) == 1 else None
    parts = {_local(n.tag): measures(n) for n in divide.nodes() if _local(n.tag) in ("unitnumerator", "unitdenominator")}
    top, bottom = parts.get("unitnumerator", []), parts.get("unitdenominator", [])
    return f"{top[0]}/{bottom[0]}" if len(top) == 1 and len(bottom) == 1 else None


def facts(sec: SecClient, filing: Filing, cache: DiskCache) -> list[dict]:
    """Every whole-company numeric fact in the filing's primary document; cached, since filings never change."""
    key = f"ixbrl|v2|{filing.url}"  # v2: facts carry the unit's measure
    cached = cache.get(key, None)
    if cached is not None:
        return json.loads(cached[0])
    try:
        doc = Document(sec.get(filing.url).body)
    except DomainError as exc:
        raise DataError(f"The filing could not be parsed: {exc}", "bad_data") from exc
    nodes = list(doc.root.nodes())
    by_id = {n.attrs["id"]: n for n in nodes if "id" in n.attrs}
    found = []
    for node in nodes:
        if node.tag != "ix:nonfraction" or "name" not in node.attrs:
            continue
        context = by_id.get(node.attrs.get("contextref"))
        if context is None or any(_local(n.tag) in DIMENSIONS for n in context.nodes()):
            continue
        fields = {_local(n.tag): n.text() for n in context.nodes()}
        value = _number(node)
        _, start, end = doc.fragment(node)
        row = node.ancestor("tr")
        found.append({"concept": node.attrs["name"], "value": None if value is None else format(value, "f"),
                      "raw": node.text(), "format": node.attrs.get("format", ""),
                      "unit": _unit(by_id.get(node.attrs.get("unitref"))),
                      "start": fields.get("startdate"), "end": fields.get("enddate") or fields.get("instant"),
                      "hidden": node.ancestor("ix:hidden") is not None, "row": row.text() if row else None,
                      "locator": f"#{node.attrs.get('id', '')} bytes [{start},{end})"})
    cache.put(key, json.dumps(found).encode(), datetime.now(timezone.utc))
    return found
