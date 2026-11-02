from datetime import datetime, timezone
from decimal import Decimal, localcontext, ROUND_DOWN

import pytest

from research_assistant.contracts import DomainError, FilingPacket, FinancialFact, SourceDocument
from research_assistant.filings import Document
from research_assistant.financials import identified, operating_margin, parse_filing_facts
from research_assistant.research import conservative_availability
from test_filing_packets import PACKET, annual, needs_packet

# Every test here parses the real 10-K in the git-ignored packet.
pytestmark = needs_packet

def parse(raw=None):
    source = (PACKET / "raw/original-10k.html").read_bytes() if raw is None else raw
    now = datetime(2026, 10, 29, tzinfo=timezone.utc)
    packet = FilingPacket(cik="0000789019", accession=annual().accn, form="10-K", filed=annual().filed,
                          period_end=annual().end, documents=[SourceDocument(role="filing", source_url="https://www.sec.gov/test",
                          snapshot_hash="a" * 64, byte_length=len(source), media_type="text/html", retrieved_at=now)])
    return parse_filing_facts(Document(source), packet, annual(), "msft-original", conservative_availability(annual().filed), now)


def test_real_original_typed_facts_and_formula():
    revenue, income, table = parse()
    assert revenue.raw_value == "245,122" and revenue.scale == 6
    assert revenue.normalized_value == Decimal("245122000000")
    assert income.normalized_value == Decimal("109433000000")
    assert revenue.basis == "US_GAAP" and revenue.scope == "consolidated"
    assert revenue.accession == income.accession == annual().accn
    assert "bytes [" in revenue.locator and table.tag == "table"
    result = operating_margin(revenue, income)
    assert result.failure is None and result.result == Decimal("0.4464429957327371676144940071")
    assert result.input_fact_ids == (revenue.id, income.id)
    with localcontext() as context:
        context.prec, context.rounding = 4, ROUND_DOWN
        assert operating_margin(revenue, income) == result
    assert FinancialFact.model_validate_json(revenue.model_dump_json()) == revenue


@pytest.mark.parametrize("old,new", [
    (b">0000789019<", b">0000320193<"),
    (b"iso4217:USD", b"iso4217:EUR"),
    (b"2023-07-01", b"2024-04-01"),
    (b"scale=\"6\"", b"scale=\"3\""),
    (b">245,122</ix:nonFraction>", b">245,123</ix:nonFraction>"),
    (b"</xbrli:entity><xbrli:period><xbrli:startDate>2023-07-01", b"<xbrli:segment>unknown scope</xbrli:segment></xbrli:entity><xbrli:period><xbrli:startDate>2023-07-01"),
])
def test_original_fact_mismatches_rejected(old, new):
    raw = (PACKET / "raw/original-10k.html").read_bytes()
    altered = raw.replace(old, new)
    assert altered != raw
    with pytest.raises(DomainError):
        parse(altered)


def test_unknown_basis_scope_are_explicit_and_not_calculable():
    raw = (PACKET / "raw/original-10k.html").read_bytes()
    # Removing both basis formulations leaves original figures but no checked basis.
    raw = raw.replace(b"accounting principles generally accepted in the United States", b"accounting principles under an unknown framework")
    raw = raw.replace(b"consolidated financial statements", b"financial records of unknown scope")
    rev, income, _ = parse(raw)
    assert rev.basis == "unknown" and rev.scope == "unknown"
    assert operating_margin(rev, income).failure == "invalid_fact"


def test_duplicate_and_conflicting_original_tags():
    raw = (PACKET / "raw/original-10k.html").read_bytes()
    doc = Document(raw)
    node = next(n for n in doc.root.nodes("ix:nonfraction") if n.attrs.get("id") == "F_3c083f9d-9cbe-4037-b6c1-310e199227a1")
    fragment, start, end = doc.fragment(node)
    duplicate = fragment.replace(b"F_3c083f9d-9cbe-4037-b6c1-310e199227a1", b"duplicate").replace(b"RevenueFromContractWithCustomerExcludingAssessedTax", b"Revenues")
    assert parse(raw[:end] + duplicate + raw[end:])[0].normalized_value == Decimal("245122000000")
    with pytest.raises(DomainError, match="Conflicting"):
        parse(raw[:end] + duplicate.replace(b"245,122", b"245,123") + raw[end:])


@pytest.mark.parametrize("value", ["0", "-1"])
def test_nonpositive_revenue_is_typed_failure(value):
    rev, income, _ = parse()
    rev = identified(rev.model_copy(update={"normalized_value": Decimal(value)}), "fact-")
    assert operating_margin(rev, income).failure == "nonpositive_revenue"


def test_missing_and_incompatible_inputs_are_typed_failures():
    rev, income, _ = parse()
    assert operating_margin(rev, None).failure == "missing_input"
    for field, value in [("issuer_cik", "0000320193"), ("accession", "0000950170-25-100235"),
                         ("start", income.start.replace(year=2022)), ("concept", "us-gaap:NetIncomeLoss")]:
        changed = income.model_copy(update={field: value})
        assert operating_margin(rev, changed).failure in {"invalid_fact", "incompatible_inputs"}
    assert operating_margin(rev, income.model_copy(update={"unit": "EUR"})).failure == "invalid_fact"
