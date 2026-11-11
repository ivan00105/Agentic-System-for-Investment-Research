"""Shape of the evaluation cases in eval/cases/: one YAML per case (PROJECT_GUIDE §8, REFERENCE §7).

Gold answers are copied from the filing document on EDGAR, never from our own tools, so the system
is not graded against itself. A gold item either cites its filing (`source`) or is computed from
other gold items in the same case (`derived`).
"""
import re
from datetime import date
from pathlib import Path

import pytest
import yaml

CASES = sorted((Path(__file__).resolve().parents[1] / "eval" / "cases").glob("*.yaml"))
SPLITS = {"dev", "held_out"}
MODES = {"check", "compare", "discover"}
# The robustness cases in REFERENCE §7; add a type here when a new kind of case needs one.
CASE_TYPES = {"check", "fiscal_period_trap", "bank", "foreign_filer", "unknown_ticker", "prompt_injection",
              "restatement", "injected_error", "missing_data", "impossible_filter", "api_failure", "look_ahead"}
BEHAVIOURS = {"answer", "answer_or_abstain", "not_available"}
ACCESSION = re.compile(r"\d{10}-\d{2}-\d{6}")


def load(path):
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def text(value):
    return isinstance(value, str) and value.strip() != ""


def number(value):
    return isinstance(value, int | float) and not isinstance(value, bool)


def check_source(source, cik, item, cutoff):
    assert {"form", "accession", "filed", "url", "location"} <= source.keys()
    assert text(source["form"]) and text(source["location"])
    assert isinstance(source["accession"], str) and ACCESSION.fullmatch(source["accession"])
    assert isinstance(source["filed"], date) and item["period_end"] <= source["filed"] <= cutoff
    folder = f"https://www.sec.gov/Archives/edgar/data/{cik}/{source['accession'].replace('-', '')}/"
    assert isinstance(source["url"], str) and source["url"].startswith(folder)


def check_gold(case, ciks):
    names = [item.get("name") for item in case["gold"]]
    assert len(names) == len(set(names))
    sourced = {item["name"] for item in case["gold"] if "source" in item}
    for item in case["gold"]:
        assert text(item["name"]) and text(item.get("metric")) and item["ticker"] in ciks
        assert number(item["value"]) and text(item["unit"]) and text(item["fiscal_period"])
        assert isinstance(item["period_end"], date) and item["period_end"] <= case["cutoff"]
        assert ("source" in item) != ("derived" in item), f"{item['name']}: give exactly one of source or derived"
        assert number(item.get("tolerance", 0)) and item.get("tolerance", 0) >= 0
        if "source" in item:
            check_source(item["source"], ciks[item["ticker"]], item, case["cutoff"])
        else:
            assert text(item["derived"]["formula"]) and item["derived"]["inputs"]
            assert set(item["derived"]["inputs"]) <= sourced


def test_cases_exist():
    assert len(CASES) >= 10


def test_related_cases_share_a_split():
    # Cases built on the same gold must not straddle dev and held_out, or the held-out set leaks (REFERENCE §7).
    cases = {path.stem: load(path) for path in CASES}
    for case in cases.values():
        for other in case.get("related", []):
            assert other in cases and cases[other]["split"] == case["split"], (case["id"], other)


def test_case_ids_are_unique_and_match_file_names():
    ids = [load(path)["id"] for path in CASES]
    assert ids == [path.stem for path in CASES] and len(ids) == len(set(ids))


@pytest.mark.parametrize("path", CASES, ids=lambda path: path.stem)
def test_case_has_required_fields_and_types(path):
    case = load(path)
    assert {"id", "split", "case_type", "mode", "source", "question", "cutoff", "companies", "expected", "gold",
            "review", "notes"} <= case.keys()
    assert case["split"] in SPLITS and case["case_type"] in CASE_TYPES and case["mode"] in MODES
    assert text(case["source"]) and text(case["question"]) and text(case["notes"])
    assert isinstance(case["cutoff"], date)

    ciks = {}
    for company in case["companies"]:
        assert text(company["ticker"]) and company["ticker"] == company["ticker"].upper()
        if case["case_type"] == "unknown_ticker":
            assert company["cik"] is None
        else:
            assert isinstance(company["cik"], int) and company["cik"] > 0 and text(company["name"])
        ciks[company["ticker"]] = company["cik"]
    assert ciks and (case["mode"] != "compare" or len(ciks) >= 2)

    expected = case["expected"]
    assert expected["behaviour"] in BEHAVIOURS
    for key in ("must_mention", "must_not"):
        assert all(text(line) for line in expected.get(key, []))
    assert isinstance(case["gold"], list) and (case["gold"] == []) == (expected["behaviour"] == "not_available")
    check_gold(case, ciks)

    assert ("injection" in case) == (case["case_type"] == "prompt_injection")
    if "injection" in case:
        assert all(text(case["injection"][key]) for key in ("tool", "target", "position", "text"))

    if case["case_type"] == "look_ahead":  # the later events to look for, which no tool can return at the cutoff
        assert expected.get("must_not")

    review = case["review"]
    assert text(review["labelled_by"]) and isinstance(review["labelled_on"], date)
    assert review["checked_by"] is None or text(review["checked_by"])
    assert review["check_note"] is None or text(review["check_note"])
