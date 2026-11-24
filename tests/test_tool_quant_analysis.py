from datetime import datetime, timezone

from sec_files import make_context

from research_assistant.tools import get_factor_exposures, get_shortlist_risk, get_strategy_lab
from research_assistant.tools.result import ToolResult, make_id


def _price_record(ticker, count=300):
    rows = [{"date": f"2025-{month:02d}-{day:02d}", "close": 100 + index,
             "adj_close": 100 + index, "split": 1, "dividend": 0}
            for index, (month, day) in enumerate(((month, day) for month in range(1, 13)
                                                  for day in range(1, 25)))]
    rows = rows[:count]
    record_id = make_id("prices", ticker)
    record = {"id": record_id, "kind": "prices", "ticker": ticker, "cik": None,
              "source": "test", "rows": rows, "start": rows[0]["date"], "end": rows[-1]["date"]}
    return record


def test_factor_exposures_use_mocked_ken_french(tmp_path, monkeypatch):
    context = make_context(tmp_path, cutoff=datetime(2026, 4, 20, tzinfo=timezone.utc))
    stock = _price_record("AAPL")
    context.records[stock["id"]] = stock

    def fake_get_prices(_args, _context):
        return ToolResult(status="ok", ids=[stock["id"]], source="test")

    monkeypatch.setattr(get_factor_exposures, "get_prices", fake_get_prices)
    monkeypatch.setattr(get_factor_exposures.factors, "five_factors", lambda _cache: {
        row["date"].replace("-", ""): {"MKT-RF": 0.01, "SMB": 0.002, "HML": 0.003,
                                       "RMW": 0.004, "CMA": 0.001, "RF": 0.0001}
        for row in stock["rows"][1:]
    })
    monkeypatch.setattr(get_factor_exposures.factors, "momentum", lambda _cache: {
        row["date"].replace("-", ""): 0.002 for row in stock["rows"][1:]
    })

    result = get_factor_exposures.run(
        get_factor_exposures.GetFactorExposuresInput(ticker="AAPL"), context
    )
    assert result.status in ("ok", "unsupported")
    if result.status == "ok":
        assert result.ids
        assert "betas" in context.records[result.ids[0]]


def test_shortlist_risk_handles_mocked_price_series(tmp_path, monkeypatch):
    context = make_context(tmp_path, cutoff=datetime(2026, 4, 20, tzinfo=timezone.utc))
    records = {ticker: _price_record(ticker, count=40) for ticker in ("AAPL", "MSFT", "SPY")}
    for record in records.values():
        context.records[record["id"]] = record

    def fake_get_prices(args, _context):
        record = records[args.ticker]
        return ToolResult(status="ok", ids=[record["id"]], source="test")

    monkeypatch.setattr(get_shortlist_risk, "get_prices", fake_get_prices)
    result = get_shortlist_risk.run(
        get_shortlist_risk.GetShortlistRiskInput(tickers=["AAPL", "MSFT"]), context
    )
    assert result.status in ("ok", "partial")
    assert result.ids


def test_strategy_lab_stops_at_the_cutoff(tmp_path, monkeypatch):
    days = ["20151230", "20151231", "20160104", "20260102"]
    monkeypatch.setattr(get_strategy_lab.factors, "five_factors", lambda _cache: {
        day: dict.fromkeys(("MKT-RF", "SMB", "HML", "RMW", "CMA", "RF"), 0.01) for day in days})
    monkeypatch.setattr(get_strategy_lab.factors, "momentum", lambda _cache: dict.fromkeys(["19261103", *days], 0.01))
    past = make_context(tmp_path, cutoff=datetime(2016, 1, 10, tzinfo=timezone.utc))
    result = get_strategy_lab.run(get_strategy_lab.GetStrategyLabInput(), past)
    spans = {item["name"]: (item["start"], item["end"], item["observations"]) for item in result.data["strategies"]}
    assert spans["value"] == ("2015-12-30", "2016-01-04", 3)
    assert spans["momentum"] == ("1926-11-03", "2016-01-04", 4)
    assert any("today's copy" in warning for warning in result.warnings)

    before = make_context(tmp_path, cutoff=datetime(1920, 1, 1, tzinfo=timezone.utc))
    assert get_strategy_lab.run(get_strategy_lab.GetStrategyLabInput(), before).status == "unsupported"
