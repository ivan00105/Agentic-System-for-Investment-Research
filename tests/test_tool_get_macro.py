import math
import statistics
from datetime import date, datetime, timezone
from decimal import Decimal
from urllib.parse import parse_qs

import httpx
import pytest
from fx_rates import weekdays
from sec_files import make_context

from research_assistant import config
from research_assistant.data import macro_fred, macro_treasury, providers
from research_assistant.tools.calculate import CalculateInput
from research_assistant.tools.calculate import run as calculate
from research_assistant.tools.get_macro import GetMacroInput, run

CUTOFF = datetime(2026, 11, 6, 23, tzinfo=timezone.utc)  # 6 Nov, 18:00 in New York: that day's rates are known
BILLS = ('Date,"4 WEEKS BANK DISCOUNT","4 WEEKS COUPON EQUIVALENT","13 WEEKS BANK DISCOUNT","13 WEEKS COUPON EQUIVALENT"\n'
         "11/09/2026,3.80,3.90,3.99,4.09\n11/06/2026,3.89,3.96,4.00,4.10\n11/05/2026,3.85,3.91,4.04,4.14\n"
         "11/04/2026,3.88,3.95,N/A,N/A\n11/03/2026,3.88,3.95,4.02,4.12\n")
CURVE = ('Date,"1 Mo","3 Mo","2 Yr","10 Yr"\n11/06/2026,4.03,4.17,4.46,4.84\n11/05/2026,4.01,4.21,4.58,4.90\n')


class Treasury:
    """A mocked home.treasury.gov: this year's files only (last year's are empty)."""

    def __init__(self):
        self.requests = []

    def __call__(self, request):
        self.requests.append(request)
        kind, year = request.url.params["type"], request.url.params["field_tdr_date_value"]
        body = {"daily_treasury_bill_rates": BILLS, "daily_treasury_yield_curve": CURVE}[kind] if year == "2026" else "Date\n"
        return httpx.Response(200, text=body)


def fred_answer(request):
    params = parse_qs(request.url.query.decode())
    if request.url.path.endswith("/releases/dates"):
        return httpx.Response(200, json={"count": 3, "release_dates": [
            {"release_id": 10, "release_name": "Consumer Price Index", "date": "2026-11-12"},
            {"release_id": 9, "release_name": "Advance Monthly Sales", "date": "2026-11-14"},
            {"release_id": 101, "release_name": "FOMC Press Release", "date": "2026-12-09"}]})
    series = params["series_id"][0]
    if series == "CPIAUCSL":
        return httpx.Response(200, json={"observations": [{"date": "2026-08-01", "value": "2.9"},
                                                          {"date": "2026-09-01", "value": "3.1"}]})
    return httpx.Response(200, json={"observations": [{"date": "2026-11-05", "value": "4.05"},
                                                      {"date": "2026-11-06", "value": "."}]})


@pytest.fixture
def treasury(monkeypatch):
    mock = Treasury()
    monkeypatch.setattr(macro_treasury, "transport", httpx.MockTransport(mock))
    monkeypatch.setattr(macro_fred.LIMITER, "wait", lambda: None)
    monkeypatch.setattr(config, "HTTP_RETRY_BACKOFF_SECONDS", 0)
    return mock


@pytest.fixture
def fred(monkeypatch, treasury):
    seen = []

    def answer(request):
        seen.append(request)
        return fred_answer(request)
    monkeypatch.setenv("FRED_API_KEY", "secret-key")
    monkeypatch.setattr(macro_fred, "transport", httpx.MockTransport(answer))
    return seen


def get(tmp_path, **args):
    context = make_context(tmp_path, cutoff=CUTOFF)
    return run(GetMacroInput(**args), context), context


def test_without_keys_treasury_gives_the_rates_and_says_what_needs_fred(tmp_path, treasury):
    result, context = get(tmp_path)
    assert result.status == "ok" and result.source == "U.S. Treasury daily rates (fallback)"
    names = [s["name"] for s in result.data["series"]]
    assert names == ["tbill_3m", "treasury_2y", "treasury_10y"]
    bill = context.records[result.data["series"][0]["latest"]["id"]]
    # 9 Nov is after the cutoff, so the latest known bill rate is 6 Nov's, stored as a fraction.
    assert (bill["kind"], bill["end"], bill["value"], bill["unit"], bill["vintage"]) == \
        ("fact", "2026-11-06", "0.040000", "ratio", None)
    assert any("FRED_API_KEY: fed_funds, cpi_inflation, unemployment" in w for w in result.warnings)
    assert "Release dates unavailable: needs FRED_API_KEY." in result.warnings
    assert "fred skipped: not configured (set FRED_API_KEY)." in result.warnings


def test_average_over_the_price_dates_feeds_a_sharpe_ratio(tmp_path, treasury):
    result, context = get(tmp_path, series=["tbill_3m"], start=date(2026, 11, 3), end=date(2026, 11, 6), horizon_days=0)
    average = result.data["series"][0]["average"]
    # 4 Nov has no 13-week rate (N/A), so three days count.
    assert average["observations"] == 3 and average["value"] == str((Decimal("12.06") / 3 / 100).quantize(Decimal("0.000001")))
    closes = [100.0, 102.0, 99.0, 101.0]
    context.remember({"id": "prices-x", "kind": "prices", "source": "yfinance", "cik": "0000320193", "rows": [
        {"date": f"2026-11-0{d}", "close": c, "adj_close": c} for d, c in zip((3, 4, 5, 6), closes, strict=True)]})
    sharpe = calculate(CalculateInput(formula="sharpe", inputs={"prices": "prices-x", "risk_free": average["id"]}), context)
    daily = [b / a - 1 for a, b in zip(closes, closes[1:], strict=False)]
    expected = (statistics.fmean(daily) * 252 - float(average["value"])) / (statistics.stdev(daily) * math.sqrt(252))
    assert sharpe.status == "ok" and sharpe.data["value"] == pytest.approx(expected, abs=1e-6)
    assert sharpe.data["cik"] == "0000320193" and sharpe.data["notes"]


def test_sharpe_refuses_a_rate_from_other_dates_or_a_latest_value(tmp_path, treasury):
    result, context = get(tmp_path, series=["tbill_3m"], start=date(2026, 11, 3), end=date(2026, 11, 6), horizon_days=0)
    context.remember({"id": "prices-x", "kind": "prices", "source": "yfinance", "rows": [
        {"date": f"2026-10-0{d}", "close": 100.0 + d, "adj_close": 100.0 + d} for d in (5, 6, 7, 8)]})
    series = result.data["series"][0]
    wrong_dates = calculate(CalculateInput(formula="sharpe", inputs={"prices": "prices-x", "risk_free": series["average"]["id"]}), context)
    assert wrong_dates.status == "invalid" and "start 2026-10-05 and end 2026-10-08" in wrong_dates.warnings[0]
    latest = calculate(CalculateInput(formula="sharpe", inputs={"prices": "prices-x", "risk_free": series["latest"]["id"]}), context)
    assert latest.status == "invalid" and "tbill_3m average" in latest.warnings[0]


def test_an_average_is_dated_by_the_observations_it_uses_so_sharpe_sees_the_gap(tmp_path, treasury):
    # Codex review: one bill rate, labelled with the asked year, passed next to a year of daily prices.
    days = weekdays(date(2025, 11, 3), date(2026, 11, 3))
    result, context = get(tmp_path, series=["tbill_3m"], start=days[0], end=days[-1], horizon_days=0)
    average = result.data["series"][0]["average"]
    assert (average["observations"], average["start"], average["end"]) == (1, "2026-11-03", "2026-11-03")
    context.remember({"id": "prices-x", "kind": "prices", "source": "yfinance", "rows": [
        {"date": d.isoformat(), "close": 100.0 + i % 5, "adj_close": 100.0 + i % 5} for i, d in enumerate(days)]})
    sharpe = calculate(CalculateInput(formula="sharpe", inputs={"prices": "prices-x", "risk_free": average["id"]}), context)
    assert len(days) == 262 and sharpe.status == "invalid"
    assert "covers 2026-11-03 to 2026-11-03, fewer days than the prices (2025-11-03 to 2026-11-03)" in sharpe.warnings[0]
    assert "shorten the price series to 2026-11-03 to 2026-11-03" in sharpe.warnings[0]


def test_fred_reads_the_vintage_published_at_the_cutoff(tmp_path, fred):
    result, context = get(tmp_path, series=["cpi_inflation", "tbill_3m"], horizon_days=40)
    assert result.status == "ok" and result.source == "FRED (St. Louis Fed)"
    observations = [parse_qs(r.url.query.decode()) for r in fred if r.url.path.endswith("/observations")]
    assert {(p["realtime_start"][0], p["realtime_end"][0]) for p in observations} == {("2026-11-06", "2026-11-06")}
    assert [p["units"][0] for p in observations] == ["pc1", "lin"]
    cpi = context.records[result.data["series"][0]["latest"]["id"]]
    # A monthly value covers its month; "." (no value) days are skipped, so the bill rate is 5 Nov's.
    assert (cpi["start"], cpi["end"], cpi["value"], cpi["vintage"]) == ("2026-09-01", "2026-09-30", "0.031000", "2026-11-06")
    assert context.records[result.data["series"][1]["latest"]["id"]]["end"] == "2026-11-05"
    calendar = context.records[result.data["releases"]["id"]]
    assert calendar["kind"] == "calendar" and calendar["start"] == "2026-11-06" and calendar["end"] == "2026-12-16"
    assert [r["release_id"] for r in calendar["releases"]] == [10, 101]  # retail sales (9) isn't a major release
    assert not treasury_used(context)


def treasury_used(context):
    return any(r.get("source") == "U.S. Treasury daily rates" for r in context.records.values())


def test_the_api_key_never_reaches_the_cache_or_an_error(tmp_path, fred, monkeypatch):
    get(tmp_path, series=["tbill_3m"], horizon_days=0)
    cached = b"".join(p.read_bytes() for p in (tmp_path / "cache" / "macro_cache").glob("*.json"))
    assert cached and b"secret-key" not in cached

    def down(request):
        raise httpx.ConnectError(f"refused for {request.url}")
    monkeypatch.setattr(macro_fred, "transport", httpx.MockTransport(down))
    result, _ = get(tmp_path / "other", series=["unemployment"], horizon_days=0)
    assert result.status == "unavailable" and "fred failed" in result.warnings[0]
    assert "api_key=***" in result.warnings[0] and "secret-key" not in str(result.warnings)


def test_a_failed_fred_call_falls_back_to_treasury_and_says_so(tmp_path, fred, monkeypatch):
    monkeypatch.setattr(macro_fred, "transport", httpx.MockTransport(lambda request: httpx.Response(500)))
    result, _ = get(tmp_path, series=["treasury_10y"], horizon_days=0)
    assert result.status == "ok" and result.data["series"][0]["source"] == "U.S. Treasury daily rates (fallback)"
    assert any(w.startswith("fred failed: FRED returned HTTP 500") for w in result.warnings)


def test_cached_years_are_not_fetched_again(tmp_path, treasury):
    get(tmp_path, series=["treasury_2y", "treasury_10y"], horizon_days=0)
    first = len(treasury.requests)
    get(tmp_path, series=["treasury_2y", "treasury_10y"], horizon_days=0)
    assert first == 2 and len(treasury.requests) == first  # one file per year, shared by both yields


def test_asking_for_what_no_provider_has_is_partial(tmp_path, treasury):
    result, _ = get(tmp_path, series=["tbill_3m", "unemployment"], horizon_days=10)
    assert result.status == "partial" and [s["name"] for s in result.data["series"]] == ["tbill_3m"]
    assert any(w.startswith("unemployment: unemployment needs FRED_API_KEY") for w in result.warnings)


def test_end_after_the_cutoff_moves_back_and_start_after_end_is_invalid(tmp_path, treasury):
    result, _ = get(tmp_path, series=["tbill_3m"], start=date(2026, 11, 3), end=date(2026, 11, 20), horizon_days=0)
    assert result.data["series"][0]["average"]["end"] == "2026-11-06"
    assert get(tmp_path, start=date(2026, 11, 6), end=date(2026, 11, 3))[0].status == "invalid"


def test_status_page_lists_both_macro_providers(monkeypatch):
    kinds = {k["kind"]: k for k in providers.status({})}
    macro = kinds["macro"]
    assert [p["name"] for p in macro["providers"]] == ["fred", "treasury"] and macro["active"] == "treasury"
    assert macro["providers"][0]["missing_env"] == ["FRED_API_KEY"] and macro["providers"][1]["status"] == "ready"
    assert "need FRED" in macro["providers"][1]["note"]
    monkeypatch.setenv("FRED_API_KEY", "x")
    assert {k["kind"]: k for k in providers.status({})}["macro"]["active"] == "fred"


def test_reports_name_the_source_and_vintage_of_a_macro_figure(tmp_path, fred):
    from research_assistant.agents.report import describe
    from research_assistant.agents.sources import chip, detail
    result, context = get(tmp_path, series=["cpi_inflation"], horizon_days=40)
    cpi = context.records[result.data["series"][0]["latest"]["id"]]
    assert "FRED (St. Louis Fed) CPIAUCSL, as published on 2026-11-06" in describe(cpi)
    shown = detail(cpi, context.records)
    assert shown["title"] == "CPI inflation (year on year), 2026-09-01 to 2026-09-30" and shown["excerpt"] == "3.1%"
    assert {"label": "As published on", "value": "2026-11-06"} in shown["rows"]
    calendar = context.records[result.data["releases"]["id"]]
    assert "2026-11-12 Consumer Price Index" in describe(calendar) and chip(calendar, context.records).startswith("Release")
