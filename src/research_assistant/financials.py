"""Immutable annual USD facts and one versioned, deterministic formula."""
from decimal import Decimal, localcontext, ROUND_HALF_EVEN
import hashlib
import re

from .contracts import Calculation, DomainError, FinancialFact
from .filings import REVENUE_TAGS


def identified(record, prefix):
    raw = record.model_dump_json(exclude={"id"}).encode()
    return record.model_copy(update={"id": prefix + hashlib.sha256(raw).hexdigest()})


def eligible_fact(fact):
    return (fact.unit == "USD" and fact.basis == "US_GAAP" and fact.scope == "consolidated"
            and fact.period_kind == "duration" and fact.start is not None
            and 330 <= (fact.end - fact.start).days <= 380 and fact.end <= fact.filed)


def operating_margin(revenue, income):
    inputs = tuple(f.id for f in (revenue, income) if f is not None)
    failure, result = None, None
    if revenue is None or income is None:
        failure = "missing_input"
    elif not all(eligible_fact(f) for f in (revenue, income)):
        failure = "invalid_fact"
    elif (revenue.concept not in {"us-gaap:" + tag for tag in REVENUE_TAGS} or income.concept != "us-gaap:OperatingIncomeLoss"
          or any(getattr(revenue, key) != getattr(income, key) for key in
                 ("issuer_cik", "unit", "start", "end", "basis", "scope", "accession", "form", "filed", "available_at", "evidence_id", "snapshot_hash"))):
        failure = "incompatible_inputs"
    elif revenue.normalized_value <= 0:
        failure = "nonpositive_revenue"
    else:
        with localcontext() as context:
            context.prec, context.rounding = 28, ROUND_HALF_EVEN
            result = income.normalized_value / revenue.normalized_value
    return identified(Calculation(id="", input_fact_ids=inputs, result=result, failure=failure), "calc-")


def parse_filing_facts(doc, packet, annual, evidence_id, available_at, retrieved_at):
    """Read visible table facts with an exact annual, undimensioned issuer context.

    This deliberately supports a small set of SEC Inline XBRL numeric transforms.
    Unsupported transforms/units or conflicting facts fail closed.
    """
    nodes = list(doc.root.nodes())
    by_id = {n.attrs["id"]: n for n in nodes if "id" in n.attrs}
    tables = list(doc.root.nodes("table"))
    full_text = doc.root.text().lower()
    basis = "US_GAAP" if ("accounting principles generally accepted in the united states" in full_text
                             or "u.s. generally accepted accounting principles" in full_text) else "unknown"
    scope = "consolidated" if "consolidated financial statements" in full_text else "unknown"
    values = {"revenue": [], "operating_income": []}
    selected_tables = {}
    for node in nodes:
        concept = node.attrs.get("name", "")
        if node.tag != "ix:nonfraction" or concept not in {"us-gaap:" + t for t in (*REVENUE_TAGS, "OperatingIncomeLoss")}:
            continue
        table = node.ancestor("table")
        context = by_id.get(node.attrs.get("contextref"))
        if table is None or context is None or node.ancestor("ix:hidden") is not None:
            continue
        fields = {n.tag.split(":")[-1]: n.text() for n in context.nodes()}
        if fields.get("startdate") != str(annual.start) or fields.get("enddate") != str(annual.end):
            continue
        if any(n.tag.split(":")[-1] in {"segment", "scenario", "explicitmember", "typedmember"} for n in context.nodes()):
            continue
        identifiers = [n for n in context.nodes() if n.tag.split(":")[-1] == "identifier"]
        if len(identifiers) != 1 or identifiers[0].attrs.get("scheme") != "http://www.sec.gov/CIK" or fields.get("identifier", "").zfill(10) != packet.cik:
            raise DomainError("Original fact context belongs to another issuer.", "issuer_mismatch")
        unit = by_id.get(node.attrs.get("unitref"))
        measures = [] if unit is None else [n.text() for n in unit.nodes() if n.tag.split(":")[-1] == "measure"]
        if measures != ["iso4217:USD"] or any(n.tag.split(":")[-1] == "divide" for n in unit.nodes()):
            raise DomainError("Original annual fact has unsupported units.", "source_format")
        raw = node.text()
        transform = node.attrs.get("format", "").split(":")[-1]
        if transform not in {"", "num-dot-decimal", "numdotdecimal", "zero-dash", "zerodash"}:
            raise DomainError("Original fact uses an unsupported numeric transformation.", "source_format")
        numeric = "0" if transform in {"zero-dash", "zerodash"} and raw in {"-", "—", "–"} else raw.replace(",", "")
        try:
            scale = int(node.attrs.get("scale", "0"))
            if not -12 <= scale <= 12 or not re.fullmatch(r"\d+(?:\.\d+)?", numeric) or node.attrs.get("sign") not in {None, "-"}:
                raise ValueError("Unsupported numeric value")
            with localcontext() as precision:
                precision.prec = max(50, len(numeric) + abs(scale) + 5)
                normalized = Decimal(numeric) * Decimal(10) ** scale
                if node.attrs.get("sign") == "-":
                    normalized = -normalized
            decimals = node.attrs.get("decimals", "")
            if decimals != "INF":
                int(decimals)
        except ValueError as exc:
            raise DomainError("Original annual fact contains an invalid number or precision.", "source_format") from exc
        fragment, start, end = doc.fragment(node)
        row = node.ancestor("tr")
        locator = f"table[{tables.index(table) + 1}]; row {row.text() if row else 'unknown'}; fact #{node.attrs.get('id', '')}; bytes [{start},{end})"
        fact = identified(FinancialFact(id="", issuer_cik=packet.cik, concept=concept, raw_value=raw,
            normalized_value=normalized, raw_unit=measures[0], unit="USD", scale=scale, decimals=decimals,
            start=annual.start, end=annual.end, basis=basis, scope=scope, accession=packet.accession,
            form=packet.form, filed=packet.filed, available_at=available_at, retrieved_at=retrieved_at,
            evidence_id=evidence_id, snapshot_hash=packet.documents[-1].snapshot_hash, locator=locator), "fact-")
        key = "operating_income" if concept == "us-gaap:OperatingIncomeLoss" else "revenue"
        values[key].append(fact)
        selected_tables[fact.id] = table
    selected = {}
    for key, candidates in values.items():
        if len({c.normalized_value for c in candidates}) > 1:
            raise DomainError(f"Conflicting original {key.replace('_', ' ')} values require source review.", "ambiguous_fact")
        selected[key] = candidates[0] if candidates else None
    if selected["revenue"] is None:
        raise DomainError("A comparable original annual revenue table is unavailable.", "source_format")
    if selected["revenue"].normalized_value != annual.val:
        raise DomainError("Original annual revenue differs from the saved SEC company-facts selection.", "ambiguous_fact")
    table = selected_tables[selected["revenue"].id]
    return selected["revenue"], selected["operating_income"], table
