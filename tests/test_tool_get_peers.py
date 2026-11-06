"""Synthetic SEC company lists and frames for a mocked SEC: never live evidence."""
from datetime import datetime, timezone

import httpx
import pytest
from sec_files import SecFiles, make_context

from research_assistant.agents.report import describe
from research_assistant.data import peers, providers
from research_assistant.tools.calculate import CalculateInput
from research_assistant.tools.calculate import run as calculate
from research_assistant.tools.get_peers import GetPeersInput, run

CUTOFF = datetime(2025, 6, 1, tzinfo=timezone.utc)  # calendar 2024 is the latest complete frame
LISTED = [(320193, "Apple Inc.", "AAPL"), (1571996, "Dell Technologies", "DELL"), (47217, "HP Inc.", "HPQ"),
          (1375365, "Super Micro Computer", "SMCI"), (1002047, "NetApp", "NTAP"), (1474432, "Pure Storage", "PSTG"),
          (858877, "Cisco Systems", "CSCO"), (1000001, "No Revenue Corp", "NORV")]
FEEDS = {"3571": [320193, 1571996, 47217, 1375365, 999999, 1000001], "3572": [1002047, 1474432], "3576": [858877]}
REVENUE = {320193: 391e9, 1571996: 88e9, 47217: 55e9, 1375365: 15e9, 1002047: 6e9, 1474432: 3e9, 858877: 54e9}


def feed(sic: str, start: int) -> str:
    ciks = FEEDS.get(sic, [])
    page = ciks[start:start + 2]  # two per page, so paging is exercised
    entries = "".join(f"<entry><content type='text/xml'><company-info><cik>{c:010d}</cik><sic>{sic}</sic>"
                      "</company-info></content></entry>" for c in page)
    more = "<link rel='next' href='x'/>" if start + 2 < len(ciks) else ""
    return f"<?xml version='1.0' encoding='ISO-8859-1' ?><feed xmlns='http://www.w3.org/2005/Atom'>{entries}{more}</feed>"


class Sec(SecFiles):
    def __call__(self, request):
        if request.url.path == "/cgi-bin/browse-edgar":
            self.paths.append(f"SIC {request.url.params['SIC']} from {request.url.params['start']}")
            return httpx.Response(200, text=feed(request.url.params["SIC"], int(request.url.params["start"])))
        return super().__call__(request)


def files():
    tickers = {"fields": ["cik", "name", "ticker", "exchange"], "data": [[c, n, t, "Nasdaq"] for c, n, t in LISTED]}
    frame = {"data": [{"cik": c, "val": v, "accn": f"0000000000-25-{c % 1000:06d}", "end": "2024-12-31",
                       "entityName": "x"} for c, v in REVENUE.items()]}
    base = "/api/xbrl/frames/us-gaap/{}/USD/CY2024.json"
    return Sec({"/files/company_tickers_exchange.json": httpx.Response(200, json=tickers),
                base.format("RevenueFromContractWithCustomerExcludingAssessedTax"): httpx.Response(200, json=frame),
                base.format("Revenues"): httpx.Response(404)})


def get(tmp_path, sec=None, **args):
    context = make_context(tmp_path, cutoff=CUTOFF, files=sec or files())
    return run(GetPeersInput(cik="320193", **args), context), context


def test_peers_share_the_sic_code_and_are_closest_in_revenue(tmp_path):
    sec = files()
    result, context = get(tmp_path, sec, count=3)
    assert result.status == "ok"
    assert [p["tickers"] for p in result.data["peers"]] == [["DELL"], ["HPQ"], ["SMCI"]]
    assert result.data["sector_benchmark"]["ticker"] == "XLK" and "approximate" in result.data["sector_benchmark"]["rule"]
    record = context.records[result.ids[0]]
    assert record["kind"] == "peers" and not record["widened"]
    # Unlisted (999999) and revenue-less (1000001) filers are left out, and the method says what was done.
    assert result.data["method"].startswith("Companies in SEC's ticker list today under SIC 3571 (Electronic "
                                            "Computers), ranked by closest 2024 revenue in SEC frames to Apple Inc.'s.")
    assert "4 listed companies considered; 1 had no positive revenue" in result.data["method"]
    assert sec.paths.count("SIC 3571 from 0") == 1 and "SIC 3571 from 4" in sec.paths
    assert any("SIC codes are coarse" in w for w in result.warnings)
    assert "Peers of Apple Inc.: Dell Technologies (DELL)" in describe(record)


def test_too_few_peers_widen_to_the_industry_group(tmp_path):
    result, context = get(tmp_path, count=5)
    assert [p["tickers"][0] for p in result.data["peers"]] == ["DELL", "HPQ", "CSCO", "SMCI", "NTAP"]
    assert [p["sic"] for p in result.data["peers"]] == [3571, 3571, 3576, 3571, 3572]
    assert "widened to SIC 3570-3579 because fewer than 5 had revenue" in result.data["method"]
    assert context.records[result.ids[0]]["widened"]


def test_a_past_cutoff_gives_the_sector_etf_but_no_peers(tmp_path):
    context = make_context(tmp_path, cutoff=CUTOFF, files=files())
    context.historical = True
    result = run(GetPeersInput(cik="320193"), context)
    assert result.status == "partial" and result.data["peers"] == [] and result.data["sector_benchmark"]["ticker"] == "XLK"
    assert any("can't be chosen as of a past cutoff" in w for w in result.warnings)


def test_relative_return_against_the_sector_etf(tmp_path):
    context = make_context(tmp_path)
    rows = [{"date": f"2026-01-0{d}", "close": c, "adj_close": c} for d, c in ((2, 100.0), (5, 110.0), (6, 120.0))]
    etf = [{"date": f"2026-01-0{d}", "close": c, "adj_close": c} for d, c in ((2, 50.0), (5, 52.0), (6, 55.0))]
    context.remember({"id": "prices-aapl", "kind": "prices", "source": "yfinance", "cik": "0000320193", "rows": rows})
    context.remember({"id": "prices-xlk", "kind": "prices", "source": "yfinance", "cik": None, "rows": etf})
    result = calculate(CalculateInput(formula="relative_return", inputs={"prices": "prices-aapl", "benchmark": "prices-xlk"}),
                       context)
    assert result.status == "ok" and result.data["unit"] == "pp" and result.data["value"] == pytest.approx(10.0)
    assert result.data["cik"] == "0000320193" and "Total returns 20.00% against 10.00%" in result.data["notes"][0]


@pytest.mark.parametrize("sic,etf", [(3571, "XLK"), (3674, "XLK"), (7370, "XLK"), (2834, "XLV"), (6022, "XLF"),
                                     (6798, "XLRE"), (1311, "XLE"), (5331, "XLP"), (5961, "XLY"), (4911, "XLU"),
                                     (2711, "XLC"), (9995, None)])
def test_sector_etf_follows_the_sic_ranges(sic, etf):
    assert (peers.sector_etf(sic) or {}).get("ticker") == etf


def test_status_page_lists_the_sic_list_under_peers():
    card = {k["kind"]: k for k in providers.status({})}["peers"]
    assert [p["name"] for p in card["providers"]] == ["sec_sic"] and "daily prices" in card["purpose"]
