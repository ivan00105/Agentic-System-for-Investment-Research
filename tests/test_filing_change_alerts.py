from types import SimpleNamespace

from sec_files import make_context

from research_assistant.finance.filing_changes import cosine_similarity, measure_changes, tfidf_similarity
from research_assistant.tools import get_filing_change_alerts
from research_assistant.tools.get_filing_change_alerts import GetFilingChangeAlertsInput


def _filing(accession, filed, report_date):
    return SimpleNamespace(
        accession=accession,
        form="10-K",
        filed=__import__("datetime").date.fromisoformat(filed),
        report_date=__import__("datetime").date.fromisoformat(report_date),
        url=f"https://example.test/{accession}.htm",
    )


def test_pure_text_similarity_is_deterministic():
    prior = "Cybersecurity risk increased because ransomware attacked customer systems."
    current = "Cybersecurity risk increased because ransomware attacked customer systems and vendors."
    cosine = cosine_similarity(current, prior)
    tfidf = tfidf_similarity(current, prior)
    assert 0 < cosine < 1
    assert 0 < tfidf < 1
    assert abs(cosine_similarity(prior, prior) - 1) < 1e-12
    assert cosine_similarity("", prior) == 0
    measured = measure_changes(current, prior)
    assert measured["new_text_share"] == 1 - measured["similarity"]


def test_host_tool_freezes_mocked_section_changes(tmp_path, monkeypatch):
    context = make_context(tmp_path)
    current = _filing("0000000001-25-000001", "2025-11-01", "2025-09-30")
    prior = _filing("0000000001-24-000001", "2024-11-01", "2024-09-30")
    monkeypatch.setattr(get_filing_change_alerts, "_annual_pair",
                        lambda context, cik, accession: (current, prior, None))

    def sections(sec, filing, cache):
        if filing is current:
            return {
                "part_i_item_1a": {"title": "Risk Factors", "text": "Cybersecurity ransomware vendor risk.",
                                   "covered_items": ["1A"], "warnings": [], "confidence": 1.0, "method": "test"},
                "part_ii_item_7": {"title": "MD&A", "text": "Revenue grew from demand.",
                                   "covered_items": ["7"], "warnings": [], "confidence": 1.0, "method": "test"},
            }
        return {
            "part_i_item_1a": {"title": "Risk Factors", "text": "Cybersecurity risk.",
                               "covered_items": ["1A"], "warnings": [], "confidence": 1.0, "method": "test"},
            "part_ii_item_7": {"title": "MD&A", "text": "Revenue grew.",
                               "covered_items": ["7"], "warnings": [], "confidence": 1.0, "method": "test"},
        }

    monkeypatch.setattr(get_filing_change_alerts.sec_sections, "sections", sections)
    result = get_filing_change_alerts.run(
        GetFilingChangeAlertsInput(cik="1", items=["1A", "7"], method="cosine"),
        context,
    )
    assert result.status == "ok"
    assert [alert["item"] for alert in result.data["alerts"]] == ["1A", "7"]
    assert len(result.ids) == 2
    for record_id in result.ids:
        record = context.records[record_id]
        assert record["kind"] == "calc"
        assert record["formula"] == "filing_change_alert"
        assert record["issued_at"] == context.cutoff.isoformat()
        assert record["inputs"]["current_accession"] == current.accession
        assert record["inputs"]["prior_accession"] == prior.accession
        assert "No LLM calculation" in record["notes"][1]


def test_missing_prior_and_bad_section_degrade_cleanly(tmp_path, monkeypatch):
    context = make_context(tmp_path)
    monkeypatch.setattr(get_filing_change_alerts, "_annual_pair",
                        lambda context, cik, accession: (None, None, "No prior 10-K before the current filing."))
    result = get_filing_change_alerts.run(
        GetFilingChangeAlertsInput(cik="1"),
        context,
    )
    assert result.status == "not_found"
    assert "No prior 10-K" in result.warnings[0]
