import json

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
