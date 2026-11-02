from datetime import datetime, timezone

import pytest
from sec_files import SecFiles, make_context

from research_assistant import config
from research_assistant.data import sec_sections
from research_assistant.tools.read_filing_section import ReadSectionInput, run

FILING = "/Archives/edgar/data/320193/000032019325000079/aapl-20250927.htm"


@pytest.fixture
def files():
    return SecFiles()


def read(tmp_path, files, cutoff=None, **args):
    context = make_context(tmp_path, files=files, **({"cutoff": cutoff} if cutoff else {}))
    return run(ReadSectionInput(cik="320193", **args), context), context


def test_risk_factors_from_the_latest_10k_as_citable_paragraphs(tmp_path, files):
    result, context = read(tmp_path, files, item="1A")
    assert result.status == "ok" and result.source == "SEC EDGAR + edgartools"
    assert result.data["filing"]["accession"] == "0000320193-25-000079" and result.data["section"] == "part_i_item_1a"
    first = result.data["chunks"][0]
    assert first["text"].startswith("Item 1A.") and "Risk Factors" in first["text"].split("\n\n")[0]
    assert "The following summarizes factors" in first["text"]
    assert first["id"] == "chunk-0000320193-25-000079-part_i_item_1a-0"
    assert context.records[first["id"]]["url"].endswith("aapl-20250927.htm")
    assert result.data["next_chunk"] is None


def test_parsed_sections_are_cached(tmp_path, files, monkeypatch):
    import edgar.documents

    real, parses = edgar.documents.parse_html, []
    monkeypatch.setattr(edgar.documents, "parse_html", lambda *a, **k: parses.append(1) or real(*a, **k))
    read(tmp_path, files, item="1A")
    read(tmp_path, files, item="7")
    assert files.paths.count(FILING) == 1 and len(parses) == 1


def test_keyword_search_returns_only_matching_paragraphs(tmp_path, files):
    result, _ = read(tmp_path, files, item="1A", query="conjunction")
    assert [c["n"] for c in result.data["chunks"]] == [1]
    ranked, _ = read(tmp_path, files, item="1A", query='conjunction "Item 7"')
    assert [c["n"] for c in ranked.data["chunks"]] == [1, 0]  # any term matches; the best match first
    assert read(tmp_path, files, item="1A", query="zeppelin")[0].warnings[-1] == "No paragraph matches those keywords."


def test_long_sections_page_on_paragraph_boundaries(tmp_path, files, monkeypatch):
    monkeypatch.setattr(config, "SECTION_PAGE_CHARS", 10)
    first, _ = read(tmp_path, files, item="1A")
    assert len(first.data["chunks"]) == 1 and first.data["next_chunk"] == 1
    second, _ = read(tmp_path, files, item="1A", start_chunk=first.data["next_chunk"])
    assert second.data["chunks"][0]["n"] == 1


def test_missing_item_lists_what_exists(tmp_path, files):
    result, _ = read(tmp_path, files, item="99")
    assert result.status == "not_found" and "part_ii_item_7" in result.data["available_sections"]


def test_named_filing_after_the_cutoff_is_refused(tmp_path, files):
    cutoff = datetime(2025, 10, 31, 10, 1, tzinfo=timezone.utc)
    result, _ = read(tmp_path, files, cutoff=cutoff, item="1A", accession="0000320193-25-000079")
    assert result.status == "invalid" and "after the cutoff" in result.warnings[0]


def test_headings_join_the_paragraph_after_them():
    text = "Item 7. MD&A\n\nOverview\n\n" + "A" * 300 + "\n\n" + "B" * 300
    assert sec_sections.chunks(text) == ["Item 7. MD&A\nOverview\n\n" + "A" * 300, "B" * 300]


def test_wrapped_lines_with_blank_lines_still_form_paragraphs():
    # TSM's 20-F layout: every visual line is followed by a blank line.
    line = "We wish to caution readers that the following important factors could affect results"
    text = "Risk Factors\n\n" + f"\n\n{line}" * 3 + " materially.\n\n" + f"{line}\n\n" * 3 + "and more."
    paragraphs = sec_sections.chunks(text)
    assert len(paragraphs) == 2
    assert paragraphs[0].startswith("Risk Factors\n") and paragraphs[0].endswith("materially.")


def test_auditor_report_inside_mdna_is_flagged():
    assert sec_sections.overrun_warning("part_ii_item_7", "... Report of Independent Registered Public Accounting Firm ...")
    assert sec_sections.overrun_warning("part_i_item_1a", "Report of Independent Registered Public Accounting Firm") is None


def test_non_utf8_filing_is_read_and_flagged():
    text, notes = sec_sections.decode(b"Company\x92s")
    assert text == "Company’s" and "Windows-1252" in notes[0]
