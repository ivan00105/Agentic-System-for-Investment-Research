from research_assistant.agents.checker import check, format_value, typed_numbers
from research_assistant.agents.draft import Draft
from research_assistant.agents.report import render

REVENUE = {"id": "fact-aaa111", "kind": "fact", "metric": "revenue", "unit": "USD", "value": "416161000000",
           "start": "2024-09-29", "end": "2025-09-27", "tag": "us-gaap:Revenues", "form": "10-K",
           "accession": "0000320193-25-000079", "filed": "2025-10-31", "filing_url": "https://www.sec.gov/x/"}
MARGIN = {"id": "calc-bbb222", "kind": "calc", "formula": "ratio", "unit": "ratio", "value": "0.319708",
          "inputs": {"numerator": "fact-ccc333", "denominator": "fact-aaa111"}, "start": "2024-09-29",
          "end": "2025-09-27", "notes": []}
CHUNK = {"id": "chunk-0000320193-25-000079-1A-4", "kind": "chunk", "form": "10-K", "accession": "0000320193-25-000079",
         "section": "1A", "n": 4, "url": "https://www.sec.gov/y.htm"}
NO_VALUE = {"id": "calc-ddd444", "kind": "calc", "formula": "pe", "unit": "x", "value": None,
            "reason": "P/E is not meaningful with a zero or negative denominator (-5)."}
RECORDS = {r["id"]: r for r in (REVENUE, MARGIN, CHUNK, NO_VALUE)}


def claim(text, citations=(), kind="fact"):
    return {"text": text, "citations": list(citations), "kind": kind}


def test_values_are_formatted_from_the_record_in_its_unit():
    def value(unit, raw):
        return format_value({"value": raw, "unit": unit})

    assert value("USD", "416161000000") == "$416.2 billion"
    assert value("USD", "-2500000") == "-$2.5 million"
    assert value("USD", "1234") == "$1,234"
    assert value("USD/shares", "7.46") == "$7.46 per share"
    assert value("shares", "14776353000") == "14.8 billion shares"
    assert value("ratio", "0.319708") == "32.0%"
    assert value("ratio", "-0.0455") == "-4.6%"
    assert value("pp", "2.0549") == "+2.1 pp" and value("pp", "-1.25") == "-1.3 pp"
    assert value("x", "28.44") == "28.4x"
    assert value("x", 1.234567) == "1.2x"  # risk results are floats


def test_placeholders_are_filled_and_count_as_citations():
    draft = Draft(key_numbers=[claim("Revenue was {fact:fact-aaa111} with an operating margin of {calc: bbb222}.")])
    report = check(draft, RECORDS)
    [item] = report.sections["key_numbers"]
    assert item.text == "Revenue was $416.2 billion with an operating margin of 32.0%."
    assert item.citations == ["fact-aaa111", "calc-bbb222"] and item.status == "supported" and not report.flags
    assert report.section_status("key_numbers") == "supported" and report.section_status("risks") == "abstained"


def test_problems_are_flagged_never_rejected():
    draft = Draft(summary=[claim("Margin was {calc:calc-zzz999} and growth about 45%.", kind="interpretation")],
                  risks=[claim("Supply is concentrated in Asia.", ["chunk-0000320193-25-000079-1A-4", "chunk-nope"]),
                         "Competition is intense."],
                  key_numbers=[claim("P/E is {calc:calc-ddd444}; the filing is {fact:chunk-0000320193-25-000079-1A-4}.")])
    report = check(draft, RECORDS)
    summary = report.sections["summary"][0]
    assert summary.text == "Margin was [missing calc:calc-zzz999] and growth about 45%."
    assert summary.status == "qualified" and report.section_status("summary") == "qualified"
    problems = [(f.where, f.problem) for f in report.flags]
    assert ("summary[0]", "{calc:calc-zzz999} is not an ID any tool returned in this run.") in problems
    assert any(where == "summary[0]" and "'45%' is typed" in p for where, p in problems)
    assert ("risks[0]", "Citation 'chunk-nope' is not an ID any tool returned in this run.") in problems
    assert report.sections["risks"][0].citations == ["chunk-0000320193-25-000079-1A-4"]
    assert report.sections["risks"][1].text == "Competition is intense."
    assert ("risks[1]", "No citation: cite the records this statement rests on.") in problems
    numbers = report.sections["key_numbers"][0]
    assert numbers.text.startswith("P/E is unavailable; the filing is [not a number:")
    assert any("zero or negative denominator" in p for _, p in problems)


def test_names_with_digits_are_not_typed_numbers():
    text = ("The fiscal 2025 10-K (Item 1A, Item 7) for FY2025, filed October 31, 2025 for the year ended "
            "2025-09-27, cites Q3 and the S&P 500 (chunk-0000320193-25-000079-1A-4).")
    assert typed_numbers(text) == []
    assert typed_numbers("Revenue rose 12% to $391 billion, a 2.5x jump.") == ["12%", "$391 billion", "2.5x"]
    # Live check 3 Nov 2026: product names were flagged as typed figures.
    assert typed_numbers("Charges on H20 and H200 parts, B200 ramps, COVID-19 effects.") == []
    assert typed_numbers("Among SIC 3674 filers, per the 10-Q and 8-Ks.") == []


def test_citations_are_accepted_in_the_forms_models_write():
    # Live check 3 Nov 2026: 34 of 38 first-draft flags were citations written as calc:hash.
    draft = Draft(risks=[claim("Supply risk.", ["calc:bbb222", "{fact: aaa111}", "fact-aaa111", "chunk:" + CHUNK["id"][6:]])])
    report = check(draft, RECORDS)
    assert not report.flags and report.sections["risks"][0].citations == ["calc-bbb222", "fact-aaa111", CHUNK["id"]]


def test_limitations_are_checked_and_render_lists_sources_and_flags():
    draft = Draft(summary=[claim("Revenue was {fact:aaa111}.")], risks=[claim("Supply risk.", [CHUNK["id"]])],
                  limitations=["Outlook model not built yet.", "About 3 segments were not checked."])
    report = check(draft, RECORDS)
    assert report.sources == ["fact-aaa111", CHUNK["id"]]
    assert [f.where for f in report.flags] == ["limitations[1]"]
    text = render(report, RECORDS, question="How big is Apple?", status="stopped_at_limit", cutoff="2026-11-03",
                  model="fake-model", plan="1. find_company", run_id="run-1")
    assert text.startswith("# How big is Apple?\n")
    assert "stopped at limit" in text and "## Plan\n\n1. find_company" in text
    assert "## Summary (supported)\n\n- Revenue was $416.2 billion. [1]" in text
    assert "## Risks (supported)\n\n- Supply risk. [2]" in text
    assert "## Bull case (abstained)\n\n- Nothing to report." in text
    assert "1. `fact-aaa111` revenue = $416.2 billion, 2024-09-29 to 2025-09-27" in text
    assert "2. `chunk-0000320193-25-000079-1A-4` 10-K 0000320193-25-000079, 1A paragraph 4" in text
    assert "## Checker flags\n\n- limitations[1]: '3' is typed" in text
