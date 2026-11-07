from decimal import Decimal

import pytest
from sec_files import SecFiles, make_context

from research_assistant.data import ixbrl
from research_assistant.filings import Document
from research_assistant.tools.get_financials import GetFinancialsInput
from research_assistant.tools.get_financials import run as get_financials
from research_assistant.tools.verify_against_filing import VerifyInput, run

FILING = "/Archives/edgar/data/320193/000032019325000079/aapl-20250927.htm"


@pytest.fixture
def apple(tmp_path):
    files = SecFiles()
    context = make_context(tmp_path, files=files)
    result = get_financials(GetFinancialsInput(cik="320193", years=2, metrics=["revenue", "operating_income", "capex"]), context)
    ids = {(v["end"], metric): v["id"] for metric, m in result.data["metrics"].items() for v in m["values"]}
    return context, ids, files


def verify(context, fact_id):
    return run(VerifyInput(fact_id=fact_id), context)


def test_companyfacts_value_matches_the_filing_table(apple):
    context, ids, _ = apple
    result = verify(context, ids["2025-09-27", "revenue"])
    assert result.status == "ok" and result.data["verdict"] == "match"
    found = result.data["found"][0]
    assert found["value"] == "416161000000" and "Total net sales" in found["row"] and found["locator"].startswith("#")
    assert context.records[result.ids[0]]["kind"] == "check"
    assert not any("tagged only in" in w for w in result.warnings)


def test_prior_year_comparative_also_matches(apple):
    context, ids, _ = apple
    assert verify(context, ids["2024-09-28", "operating_income"]).data["verdict"] == "match"


def test_injected_wrong_value_is_a_mismatch(apple):
    context, ids, _ = apple
    wrong = {**context.records[ids["2025-09-27", "revenue"]], "id": "fact-injected", "value": "41616100000"}
    context.remember(wrong)
    result = verify(context, "fact-injected")
    assert result.data["verdict"] == "mismatch" and "not 41616100000" in result.warnings[0]


def test_untagged_fact_is_not_in_filing(apple):
    context, ids, _ = apple
    result = verify(context, ids["2025-09-27", "capex"])  # the trimmed filing has no cash-flow statement
    assert result.data["verdict"] == "not_in_filing"


def test_parsed_facts_are_cached(apple, monkeypatch):
    context, ids, files = apple
    parses = []
    monkeypatch.setattr(ixbrl, "Document", lambda raw: parses.append(1) or Document(raw))
    verify(context, ids["2025-09-27", "revenue"])
    verify(context, ids["2025-09-27", "operating_income"])
    assert files.paths.count(FILING) == 1 and len(parses) == 1


def test_only_fact_ids_are_accepted(apple):
    context, _, _ = apple
    assert verify(context, "calc-123").status == "invalid"


def test_number_formats_scale_and_sign():
    html = b'''<html><body>
    <ix:nonFraction name="a" contextRef="c" scale="6" format="ixt:num-dot-decimal">1,234.5</ix:nonFraction>
    <ix:nonFraction name="b" contextRef="c" sign="-" format="ixt:numdotdecimal">7</ix:nonFraction>
    <ix:nonFraction name="c" contextRef="c" format="ixt:fixed-zero">-</ix:nonFraction>
    <ix:nonFraction name="d" contextRef="c" format="ixt-sec:numwordsen">five</ix:nonFraction></body></html>'''
    nodes = {n.attrs["name"]: n for n in Document(html).root.nodes("ix:nonfraction")}
    assert ixbrl._number(nodes["a"]) == Decimal("1234500000")
    assert ixbrl._number(nodes["b"]) == Decimal(-7)
    assert ixbrl._number(nodes["c"]) == Decimal(0)
    assert ixbrl._number(nodes["d"]) is None


def test_a_value_in_another_currency_is_not_a_match(apple):
    context, ids, _ = apple
    context.remember({**context.records[ids["2025-09-27", "revenue"]], "id": "fact-cny", "unit": "CNY"})
    result = verify(context, "fact-cny")
    assert result.data["verdict"] == "not_in_filing" and any("USD" in w for w in result.warnings)


def test_an_unreadable_number_is_unverified_not_a_mismatch(apple, monkeypatch):
    context, ids, _ = apple
    monkeypatch.setattr(ixbrl, "_number", lambda node: None)
    result = verify(context, ids["2025-09-27", "revenue"])
    assert result.data["verdict"] == "unverified" and "could not be read" in result.warnings[0]


def test_a_cover_count_the_tag_cuts_off_is_checked_against_the_tag(tmp_path):
    context = make_context(tmp_path)
    result = get_financials(GetFinancialsInput(cik="1577552", metrics=["shares_outstanding"], years=1), context)
    shares = result.data["metrics"]["shares_outstanding"]["values"][0]
    check = verify(context, shares["id"])
    assert check.data["verdict"] == "match" and check.data["expected"] == "1858037427"
    assert any("the page prints, 18580374278" in w for w in check.warnings)
