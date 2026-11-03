from sec_files import SecFiles, make_context

from research_assistant.tools.find_company import FindCompanyInput, run


def find(tmp_path, query, files=None):
    context = make_context(tmp_path, files=files)
    return run(FindCompanyInput(query=query), context), context


def test_exact_ticker_returns_one_company_with_profile(tmp_path):
    result, context = find(tmp_path, "aapl")
    assert result.status == "ok" and result.ids == ["company-0000320193"]
    apple = result.data["matches"][0]
    assert (apple["name"], apple["tickers"], apple["sic"], apple["fiscal_year_end"]) == ("Apple Inc.", ["AAPL"], 3571, "0926")
    assert not apple["foreign_filer"] and not apple["financial_sector"]
    assert context.records["company-0000320193"]["sic_description"] == "Electronic Computers"


def test_share_classes_are_one_issuer(tmp_path):
    result, _ = find(tmp_path, "GOOG")
    assert [m["cik"] for m in result.data["matches"]] == ["0001652044"]
    assert set(result.data["matches"][0]["tickers"]) >= {"GOOG", "GOOGL"}


def test_dotted_ticker_matches_sec_dash_form(tmp_path):
    result, _ = find(tmp_path, "brk.b")
    assert result.data["matches"][0]["tickers"] == ["BRK-B"]


def test_cik_query(tmp_path):
    result, _ = find(tmp_path, "CIK 19617")
    assert result.data["matches"][0]["name"].upper().startswith("JPMORGAN")


def test_bank_is_flagged(tmp_path):
    result, _ = find(tmp_path, "JPM")
    assert result.data["matches"][0]["financial_sector"]
    assert any("operating income" in w for w in result.warnings)


def test_foreign_filer_is_flagged(tmp_path):
    result, _ = find(tmp_path, "TSM")
    assert result.data["matches"][0]["foreign_filer"]
    assert any("IFRS" in w for w in result.warnings)


def test_name_search_ranks_the_closest_name_first_without_profiles(tmp_path):
    files = SecFiles()
    result, _ = find(tmp_path, "apple", files)
    names = [m["name"] for m in result.data["matches"]]
    assert names[0] == "Apple Inc." and len(names) >= 2
    assert not any("/submissions/" in p for p in files.paths)


def test_unlisted_name_falls_back_to_all_filers(tmp_path):
    result, _ = find(tmp_path, "Lehman Brothers Holdings")
    match = result.data["matches"][0]
    assert (match["cik"], match["listed"]) == ("0000806085", False)
    assert result.source.startswith("SEC all-filer names")
    assert any("not in SEC's current ticker list" in w for w in result.warnings)


def test_no_match_is_not_found(tmp_path):
    result, _ = find(tmp_path, "Zzyzx Quantum Unobtainium")
    assert result.status == "not_found" and result.ids == []


def test_too_many_matches_are_counted_not_dropped(tmp_path, monkeypatch):
    from research_assistant import config
    monkeypatch.setattr(config, "FIND_COMPANY_MAX_MATCHES", 1)
    result, _ = find(tmp_path, "apple")
    assert len(result.data["matches"]) == 1
    assert any("showing the best 1" in w for w in result.warnings)


def test_filer_without_an_annual_report_points_to_a_predecessor(tmp_path):
    import json

    import httpx
    from sec_files import FIXTURES

    payload = json.loads((FIXTURES / "submissions_AAPL.json").read_text())
    recent = payload["filings"]["recent"]
    recent["form"] = ["8-K" if form == "10-K" else form for form in recent["form"]]
    files = SecFiles({"/submissions/CIK0000320193.json": httpx.Response(200, json=payload)})
    result, _ = find(tmp_path, "AAPL", files)
    assert not result.data["matches"][0]["has_annual_report"]
    assert any("predecessor CIK" in w for w in result.warnings)
