import json
from decimal import Decimal

import httpx
from sec_files import FIXTURES, SecFiles, make_context

from research_assistant.tools.screen import ScreenInput, run

UNIVERSE = ["AAPL", "MSFT", "NVDA", "GOOGL", "JPM"]


def screen(tmp_path, files=None, **args):
    context = make_context(tmp_path, files=files)
    return run(ScreenInput(**args), context), context


def test_filters_rank_and_counts(tmp_path):
    result, context = screen(tmp_path, universe=UNIVERSE, year=2024, rank_by="operating_margin", top_k=2, filters=[
        {"metric": "operating_margin", "op": ">", "value": 0.25}, {"metric": "revenue_growth", "op": ">", "value": 0.05}])
    assert result.status == "ok" and result.source == "SEC frames"
    assert [c["tickers"][0] for c in result.data["candidates"]] == ["NVDA", "MSFT"]
    assert result.data["counts"] == {"screened": 5, "eligible": 3, "failed": 1, "unknown": 1, "unranked": 0, "returned": 2}
    assert result.data["candidates"][0]["values"]["operating_margin"] == str(round(81453 / 130497, 6))
    rows = {r["cik"]: r for r in context.records[result.ids[0]]["rows"]}
    assert rows["0000320193"]["eligibility"] == "fail" and rows["0000019617"]["eligibility"] == "unknown"
    assert "restated, not point-in-time" in result.warnings[0]


def test_frames_read_us_gaap_tags_only(tmp_path):
    # An IFRS filer's USD frame holds only convenience translations, so ifrs-full tags are never fetched.
    files = SecFiles()
    screen(tmp_path, files, universe=UNIVERSE, year=2024, rank_by="revenue")
    frames = [p for p in files.paths if p.startswith("/api/xbrl/frames/")]
    assert frames and all(p.startswith("/api/xbrl/frames/us-gaap/") for p in frames)


def test_ties_break_on_cik_not_name(tmp_path):
    path = "/api/xbrl/frames/us-gaap/NetIncomeLoss/USD/CY2024.json"
    frame = json.loads((FIXTURES / "frame_NetIncomeLoss_CY2024.json").read_text())
    for row in frame["data"]:
        row["val"] = 1000
    files = SecFiles({path: httpx.Response(200, json=frame)})
    result, _ = screen(tmp_path, files, universe=["AAPL", "JPM"], year=2024, rank_by="net_income")
    assert [c["cik"] for c in result.data["candidates"]] == ["0000019617", "0000320193"]


def test_unknown_never_passes(tmp_path):
    result, _ = screen(tmp_path, universe=UNIVERSE, year=2024, rank_by="revenue",
                       filters=[{"metric": "fcf", "op": ">", "value": 0}])
    assert result.data["counts"]["eligible"] == 0 and result.data["counts"]["unknown"] == 5
    assert result.data["candidates"] == []


def test_sic_filter_reads_the_industry_of_passing_companies_only(tmp_path):
    files = SecFiles()
    result, _ = screen(tmp_path, files, universe=["AAPL", "JPM", "MSFT"], year=2024, rank_by="net_income",
                       sic_prefixes=["357"], filters=[{"metric": "net_income", "op": ">", "value": 9e10}])
    assert [c["tickers"] for c in result.data["candidates"]] == [["AAPL"]]
    assert result.data["candidates"][0]["sic"] == 3571
    assert "/submissions/CIK0000019617.json" not in files.paths  # JPM already failed on net income


def test_whole_frame_universe_is_labelled(tmp_path):
    result, _ = screen(tmp_path, year=2024, rank_by="net_income", top_k=10)
    assert result.data["counts"]["screened"] == 5
    assert any("survivorship" in w for w in result.warnings)


def test_unknown_ticker_and_incomplete_year(tmp_path):
    result, _ = screen(tmp_path, universe=["AAPL", "NOPE"], year=2024, rank_by="revenue")
    assert any(w.startswith("NOPE: no SEC filer") for w in result.warnings)
    future, _ = screen(tmp_path, year=2026, rank_by="revenue")
    assert future.status == "invalid" and "latest is 2025" in future.warnings[0]


def frames_2025(**tags):
    """Calendar-2025 SEC frames from rows (cik, name, value, period end); other frames are 404."""
    return SecFiles({f"/api/xbrl/frames/us-gaap/{tag}/USD/CY2025.json": httpx.Response(200, json={"data": [
        {"cik": cik, "entityName": name, "val": val, "accn": "a", "end": end} for cik, name, val, end in rows]})
        for tag, rows in tags.items()})


# Real CY2025 SEC frame values (Nov 2026): a screen of every SEC filer ranked BitMine and UDR on top.
UDR, BITMINE, BROWN_FORMAN, EKSO = (74208, "UDR, Inc."), (1829311, "BITMINE"), (14693, "BROWN-FORMAN"), (1549084, "EKSO")


def outliers():
    return frames_2025(
        OperatingIncomeLoss=[(*UDR, 553606000, "2025-12-31"), (*BITMINE, 444211000, "2025-08-31"),
                             (*BROWN_FORMAN, 1001000000, "2026-04-30"), (*EKSO, -13326000, "2025-12-31")],
        RevenueFromContractWithCustomerExcludingAssessedTax=[
            (*UDR, 11361000, "2025-12-31"), (*BITMINE, 6095000, "2025-08-31"),
            (*BROWN_FORMAN, 3928000000, "2026-04-30"),
            (*EKSO, 71604000, "2026-05-31")],  # Ekso's CIK after a reverse merger: the new company's year
        Revenues=[(*UDR, 1712317000, "2025-12-31")],
        RevenueFromContractWithCustomerIncludingAssessedTax=[(*BROWN_FORMAN, 5082000000, "2026-04-30"),
                                                             (*EKSO, 12799000, "2025-12-31")])


def test_margin_outliers_are_aligned_or_flagged(tmp_path):
    result, context = screen(tmp_path, outliers(), universe=["74208", "1829311", "14693", "1549084"], year=2025,
                             rank_by="operating_margin", filters=[{"metric": "operating_margin", "op": ">", "value": 0.25}])
    margins = {c["cik"]: c["values"]["operating_margin"] for c in result.data["candidates"]}
    # UDR's contract revenue is a slice of its total; the excise-tax-inclusive figure never replaces net sales.
    assert margins == {"0000074208": str(round(Decimal(553606000) / 1712317000, 6)),
                       "0000014693": str(round(Decimal(1001000000) / 3928000000, 6))}
    rows = {r["cik"]: r for r in context.records[result.ids[0]]["rows"]}
    assert rows["0001829311"]["eligibility"] == "unknown"
    assert rows["0001829311"]["checks"] == ["unknown: operating_margin 7,288% is above 100%: income beyond revenue "
                                            "(gains, other income) or revenue under a tag that isn't read"]
    assert rows["0001829311"]["values"]["operating_margin"] == str(round(Decimal(444211000) / 6095000, 6))  # kept
    assert rows["0001549084"]["checks"] == ["unknown: operating_margin inputs are for different fiscal years "
                                            "(ending 2025-12-31, 2026-05-31)"]


def test_a_flagged_rank_value_is_counted_not_ranked(tmp_path):
    result, context = screen(tmp_path, outliers(), universe=["74208", "1829311"], year=2025, rank_by="operating_margin")
    assert [c["cik"] for c in result.data["candidates"]] == ["0000074208"]
    assert result.data["counts"]["unranked"] == 1
    assert any(w.startswith("1 eligible companies were not ranked because their operating_margin") for w in result.warnings)
    rows = {r["cik"]: r for r in context.records[result.ids[0]]["rows"]}
    assert rows["0001829311"]["flags"] == ["operating_margin 7,288% is above 100%: income beyond revenue (gains, "
                                           "other income) or revenue under a tag that isn't read"]


def test_a_historical_run_refuses_to_screen(tmp_path):
    # Codex review: frames hold today's latest-filed values, so a past cutoff could see later filings.
    context = make_context(tmp_path)
    context.historical = True
    result = run(ScreenInput(universe=UNIVERSE, year=2024, rank_by="revenue"), context)
    assert result.status == "invalid" and "cutoff" in result.warnings[0] and result.data is None


def test_a_larger_total_from_another_filing_does_not_replace_contract_revenue(tmp_path):
    # Second review: a total from an older filing must not override a later corrected figure.
    files = SecFiles({f"/api/xbrl/frames/us-gaap/{tag}/USD/CY2025.json": httpx.Response(200, json={"data": [
        {"cik": UDR[0], "entityName": UDR[1], "val": val, "accn": accn, "end": "2025-12-31"}]})
        for tag, val, accn in (("RevenueFromContractWithCustomerExcludingAssessedTax", 11361000, "accn-new"),
                               ("Revenues", 1712317000, "accn-old"))})
    result, context = screen(tmp_path, files, universe=["74208"], year=2025, rank_by="revenue")
    assert Decimal(result.data["candidates"][0]["values"]["revenue"]) == 11361000
    [row] = context.records[result.ids[0]]["rows"]
    assert row["notes"] == ["revenue: a larger us-gaap:Revenues total (1712317000) is in filing accn-old, not accn-new; "
                            "the us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax value is kept."]
    assert any(w.startswith("1 companies have a larger revenue total in another filing") for w in result.warnings)
