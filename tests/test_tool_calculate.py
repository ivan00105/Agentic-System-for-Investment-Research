from decimal import Decimal

import httpx
import pytest
from fx_rates import Frankfurter
from sec_files import make_context

from research_assistant.data import fx_frankfurter
from research_assistant.tools.calculate import CalculateInput, run
from research_assistant.tools.get_financials import GetFinancialsInput
from research_assistant.tools.get_financials import run as get_financials


@pytest.fixture
def apple(tmp_path):
    context = make_context(tmp_path)
    result = get_financials(GetFinancialsInput(cik="320193", years=3, metrics=[
        "revenue", "operating_income", "net_income", "operating_cash_flow", "capex", "stockholders_equity",
        "shares_outstanding"]), context)
    ids = {(v["end"], metric): v["id"] for metric, m in result.data["metrics"].items() for v in m["values"]}
    return context, ids


def calc(context, formula, **inputs):
    return run(CalculateInput(formula=formula, inputs=inputs), context)


def prices(context, id_, rows, source="yfinance"):
    context.remember({"id": id_, "kind": "prices", "source": source, "ticker": id_, "rows": rows})
    return id_


def test_operating_margin_is_cited_and_remembered(apple):
    context, ids = apple
    result = calc(context, "ratio", numerator=ids["2025-09-27", "operating_income"], denominator=ids["2025-09-27", "revenue"])
    assert result.status == "ok" and result.source == "calculate"
    assert Decimal(result.data["value"]) == round(Decimal(133050) / Decimal(416161), 6)
    assert result.data["inputs"]["numerator"] == ids["2025-09-27", "operating_income"]
    assert context.records[result.ids[0]]["unit"] == "ratio"


def test_same_inputs_give_the_same_calc_id(apple):
    context, ids = apple
    args = {"numerator": ids["2025-09-27", "net_income"], "denominator": ids["2025-09-27", "revenue"]}
    assert calc(context, "ratio", **args).ids == calc(context, "ratio", **args).ids


def test_margin_change_in_points_from_two_margins(apple):
    context, ids = apple
    margins = [calc(context, "ratio", numerator=ids[end, "operating_income"], denominator=ids[end, "revenue"]).ids[0]
               for end in ("2025-09-27", "2024-09-28")]
    result = calc(context, "change_pp", current=margins[0], previous=margins[1])
    expected = (Decimal(133050) / Decimal(416161) - Decimal(123216) / Decimal(391035)) * 100
    assert result.data["unit"] == "pp" and Decimal(result.data["value"]) == pytest.approx(expected, abs=Decimal("0.001"))


def test_growth_of_revenue_year_on_year(apple):
    context, ids = apple
    result = calc(context, "growth", current=ids["2025-09-27", "revenue"], previous=ids["2024-09-28", "revenue"])
    assert Decimal(result.data["value"]) == round(Decimal(416161 - 391035) / Decimal(391035), 6)
    assert result.data["notes"] == []


def test_growth_rejects_two_different_metrics(apple):
    context, ids = apple
    result = calc(context, "growth", current=ids["2025-09-27", "revenue"], previous=ids["2024-09-28", "net_income"])
    assert result.status == "invalid" and "revenue" in result.warnings[0]


def test_ratio_rejects_mismatched_periods(apple):
    context, ids = apple
    result = calc(context, "ratio", numerator=ids["2025-09-27", "net_income"], denominator=ids["2024-09-28", "revenue"])
    assert result.status == "invalid" and "different periods" in result.warnings[0]


def test_return_on_equity_flags_mixing_a_balance_with_a_flow(apple):
    context, ids = apple
    result = calc(context, "ratio", numerator=ids["2025-09-27", "net_income"],
                  denominator=ids["2025-09-27", "stockholders_equity"])
    assert result.status == "ok" and "year-end balance" in result.data["notes"][0]


def test_free_cash_flow_is_labelled_non_gaap(apple):
    context, ids = apple
    result = calc(context, "fcf", operating_cash_flow=ids["2025-09-27", "operating_cash_flow"],
                  capex=ids["2025-09-27", "capex"])
    assert result.data["value"] == str(111482000000 - 12715000000) and "non-GAAP" in result.data["notes"][0]


def test_unknown_ids_and_missing_roles_are_invalid(apple):
    context, ids = apple
    assert calc(context, "ratio", numerator="fact-made-up", denominator=ids["2025-09-27", "revenue"]).status == "invalid"
    missing = calc(context, "ratio", numerator=ids["2025-09-27", "revenue"])
    assert missing.status == "invalid" and "denominator" in missing.warnings[0]


def test_valuation_chain_market_cap_then_pe(apple):
    context, ids = apple
    series = prices(context, "prices-aapl", [{"date": "2026-10-30", "close": 250.0, "adj_close": 250.0}])
    cap = calc(context, "market_cap", prices=series, shares=ids["2026-07-17", "shares_outstanding"])
    assert cap.data["value"] == str(250 * 14594180000) and "2026-10-30" in cap.data["notes"][0]
    pe = calc(context, "pe", market_cap=cap.ids[0], net_income=ids["2025-09-27", "net_income"])
    assert Decimal(pe.data["value"]) == round(Decimal(250 * 14594180000) / Decimal(112010000000), 6)


def test_market_cap_skips_a_blank_close(apple):
    # Live check 3 Nov 2026: Yahoo listed the current day with a NaN close and market_cap crashed.
    context, ids = apple
    series = prices(context, "prices-nvda", [{"date": "2026-10-30", "close": 250.0, "adj_close": 250.0},
                                             {"date": "2026-11-02", "close": float("nan"), "adj_close": None}])
    cap = calc(context, "market_cap", prices=series, shares=ids["2026-07-17", "shares_outstanding"])
    assert cap.status == "ok" and cap.data["value"] == str(250 * 14594180000) and "2026-10-30" in cap.data["notes"][0]


def test_price_risk_and_beta_need_one_provider(apple):
    context, _ = apple
    rows = [{"date": f"2026-01-0{d}", "close": c, "adj_close": c} for d, c in enumerate([100.0, 102.0, 99.0, 101.0], 1)]
    stock = prices(context, "prices-x", rows)
    assert calc(context, "volatility", prices=stock).status == "ok"
    assert calc(context, "max_drawdown", prices=stock).data["value"] == pytest.approx(-0.029412, abs=1e-6)
    other = prices(context, "prices-spy", rows, source="tiingo")
    beta = calc(context, "beta", prices=stock, benchmark=other)
    assert beta.status == "invalid" and "same provider" in beta.warnings[0]


def test_not_meaningful_result_is_recorded_with_its_reason(apple):
    context, ids = apple
    context.remember({**context.records[ids["2025-09-27", "net_income"]], "id": "fact-loss", "value": "-5"})
    series = prices(context, "prices-aapl", [{"date": "2026-10-30", "close": 250.0, "adj_close": 250.0}])
    cap = calc(context, "market_cap", prices=series, shares=ids["2026-07-17", "shares_outstanding"])
    pe = calc(context, "pe", market_cap=cap.ids[0], net_income="fact-loss")
    assert pe.status == "unsupported" and pe.data["value"] is None and "zero or negative" in pe.data["reason"]


def add_bank(context):
    result = get_financials(GetFinancialsInput(cik="19617", years=2, metrics=["revenue", "net_income"]), context)
    return {(v["end"], metric): v["id"] for metric, m in result.data["metrics"].items() for v in m["values"]}


def test_growth_across_two_companies_is_rejected(apple):
    # Codex review: Apple FY2025 revenue "grew" 134% over JPMorgan FY2024 revenue and came back ok.
    context, ids = apple
    bank = add_bank(context)
    result = calc(context, "growth", current=ids["2025-09-27", "revenue"], previous=bank["2024-12-31", "revenue"])
    assert result.status == "invalid" and "different companies" in result.warnings[0]


def test_results_carry_their_company_so_chains_stay_checked(apple):
    context, ids = apple
    bank = add_bank(context)
    margin = calc(context, "ratio", numerator=ids["2025-09-27", "net_income"], denominator=ids["2025-09-27", "revenue"])
    assert margin.data["cik"] == "0000320193"
    bank_margin = calc(context, "ratio", numerator=bank["2025-12-31", "net_income"], denominator=bank["2025-12-31", "revenue"])
    mixed = calc(context, "change_pp", current=bank_margin.ids[0], previous=margin.ids[0])
    assert mixed.status == "invalid" and "different companies" in mixed.warnings[0]


def test_market_cap_rejects_another_companys_prices(apple):
    context, ids = apple
    context.remember({"id": "prices-jpm", "kind": "prices", "source": "yfinance", "ticker": "JPM", "cik": "0000019617",
                      "rows": [{"date": "2026-10-30", "close": 300.0, "adj_close": 300.0}]})
    result = calc(context, "market_cap", prices="prices-jpm", shares=ids["2026-07-17", "shares_outstanding"])
    assert result.status == "invalid" and "different companies" in result.warnings[0]


def test_beta_against_a_benchmark_is_not_a_company_mix(apple):
    context, _ = apple
    rows = [{"date": f"2026-01-0{d}", "close": c, "adj_close": c} for d, c in enumerate([100.0, 102.0, 99.0, 101.0], 1)]
    context.remember({"id": "prices-aapl", "kind": "prices", "source": "yfinance", "cik": "0000320193", "rows": rows})
    context.remember({"id": "prices-spy", "kind": "prices", "source": "yfinance", "cik": None, "rows": rows})
    assert calc(context, "beta", prices="prices-aapl", benchmark="prices-spy").status == "ok"


def test_market_cap_scales_shares_for_a_split_after_the_count(apple):
    # Codex review: 10 shares at $100, then a 2-for-1 split, is 20 shares at $50, still $1,000 - not $500.
    context, ids = apple
    series = prices(context, "prices-split", [{"date": "2026-07-10", "close": 200.0, "adj_close": 100.0, "split": 1.0},
                                              {"date": "2026-08-03", "close": 101.0, "adj_close": 101.0, "split": 2.0},
                                              {"date": "2026-10-30", "close": 105.0, "adj_close": 105.0, "split": 1.0}])
    cap = calc(context, "market_cap", prices=series, shares=ids["2026-07-17", "shares_outstanding"])
    assert cap.data["value"] == str(105 * 14594180000 * 2)
    assert any("split" in note and "2026-08-03" in note for note in cap.data["notes"])


def test_market_cap_says_when_splits_could_not_be_checked(apple):
    context, ids = apple
    series = prices(context, "prices-short", [{"date": "2026-10-30", "close": 105.0, "adj_close": 105.0, "split": 1.0}])
    cap = calc(context, "market_cap", prices=series, shares=ids["2026-07-17", "shares_outstanding"])
    assert cap.status == "ok" and any("could not be checked" in note for note in cap.data["notes"])


def test_market_cap_rejects_revenue_as_the_share_count(apple):
    # Codex review: revenue was accepted as the share count and came back as a clean market cap.
    context, ids = apple
    series = prices(context, "prices-aapl", [{"date": "2026-10-30", "close": 250.0, "adj_close": 250.0}])
    result = calc(context, "market_cap", prices=series, shares=ids["2025-09-27", "revenue"])
    assert result.status == "invalid" and "share count" in result.warnings[0]


def test_pe_rejects_eps_as_net_income(apple):
    context, ids = apple
    eps = {**context.records[ids["2025-09-27", "net_income"]], "id": "fact-eps", "metric": "eps_diluted",
           "unit": "USD/shares", "value": "7.46"}
    context.remember(eps)
    series = prices(context, "prices-aapl", [{"date": "2026-10-30", "close": 250.0, "adj_close": 250.0}])
    cap = calc(context, "market_cap", prices=series, shares=ids["2026-07-17", "shares_outstanding"])
    result = calc(context, "pe", market_cap=cap.ids[0], net_income="fact-eps")
    assert result.status == "invalid" and "USD amount" in result.warnings[0]


def test_valuation_needs_a_market_cap_result(apple):
    context, ids = apple
    result = calc(context, "ps", market_cap=ids["2025-09-27", "net_income"], revenue=ids["2025-09-27", "revenue"])
    assert result.status == "invalid" and "market_cap" in result.warnings[0]


def test_free_cash_flow_rejects_a_share_count_as_capex(apple):
    context, ids = apple
    result = calc(context, "fcf", operating_cash_flow=ids["2025-09-27", "operating_cash_flow"],
                  capex=ids["2026-07-17", "shares_outstanding"])
    assert result.status == "invalid" and "USD amount" in result.warnings[0]


def test_market_cap_needs_a_price_series(apple):
    context, ids = apple
    result = calc(context, "market_cap", prices=ids["2025-09-27", "revenue"], shares=ids["2026-07-17", "shares_outstanding"])
    assert result.status == "invalid" and "price series" in result.warnings[0]


def test_market_cap_is_unsupported_for_a_foreign_filer(apple):
    # Second review: BABA's ADS is 8 ordinary shares, so ADS price x ordinary shares gave 8 times the market cap.
    context, ids = apple
    context.remember({**context.records[ids["2026-07-17", "shares_outstanding"]], "id": "fact-ordinary", "form": "20-F"})
    series = prices(context, "prices-baba", [{"date": "2026-10-30", "close": 250.0, "adj_close": 250.0}])
    cap = calc(context, "market_cap", prices=series, shares="fact-ordinary")
    assert cap.status == "unsupported" and cap.data["value"] is None and "20-F" in cap.data["reason"]
    pe = calc(context, "pe", market_cap=cap.ids[0], net_income=ids["2025-09-27", "net_income"])
    assert pe.status == "unsupported" and "20-F" in pe.data["reason"]


def test_market_cap_is_unsupported_when_the_share_basis_is_unknown(apple):
    context, ids = apple
    shares = {k: v for k, v in context.records[ids["2026-07-17", "shares_outstanding"]].items() if k != "form"}
    context.remember({**shares, "id": "fact-no-form"})
    series = prices(context, "prices-aapl", [{"date": "2026-10-30", "close": 250.0, "adj_close": 250.0}])
    cap = calc(context, "market_cap", prices=series, shares="fact-no-form")
    assert cap.status == "unsupported" and "share basis" in cap.data["reason"]


def test_pe_rejects_revenue_as_net_income(apple):
    # Second review: a USD revenue fact passed the unit check as net income and gave a clean P/E.
    context, ids = apple
    series = prices(context, "prices-aapl", [{"date": "2026-10-30", "close": 250.0, "adj_close": 250.0}])
    cap = calc(context, "market_cap", prices=series, shares=ids["2026-07-17", "shares_outstanding"])
    result = calc(context, "pe", market_cap=cap.ids[0], net_income=ids["2025-09-27", "revenue"])
    assert result.status == "invalid" and "not net_income" in result.warnings[0]
    pb = calc(context, "pb", market_cap=cap.ids[0], equity=ids["2025-09-27", "net_income"])
    assert pb.status == "invalid" and "not stockholders_equity" in pb.warnings[0]


def test_fcf_yield_needs_an_fcf_result(apple):
    context, ids = apple
    series = prices(context, "prices-aapl", [{"date": "2026-10-30", "close": 250.0, "adj_close": 250.0}])
    cap = calc(context, "market_cap", prices=series, shares=ids["2026-07-17", "shares_outstanding"])
    result = calc(context, "fcf_yield", fcf=ids["2025-09-27", "operating_cash_flow"], market_cap=cap.ids[0])
    assert result.status == "invalid" and "not fcf" in result.warnings[0]
    swapped = calc(context, "fcf", operating_cash_flow=ids["2025-09-27", "capex"], capex=ids["2025-09-27", "operating_cash_flow"])
    assert swapped.status == "invalid"


def test_ratio_still_takes_any_two_amounts(apple):
    context, ids = apple
    result = calc(context, "ratio", numerator=ids["2025-09-27", "operating_cash_flow"], denominator=ids["2025-09-27", "revenue"])
    assert result.status == "ok"


@pytest.fixture
def baba(tmp_path):
    context = make_context(tmp_path)
    result = get_financials(GetFinancialsInput(cik="1577552", years=1, metrics=["shares_outstanding", "net_income"]),
                            context)
    metrics = result.data["metrics"]
    return context, metrics["shares_outstanding"]["values"][0], metrics["ordinary_shares_per_ads"]["values"][0]


def test_ads_market_cap_divides_the_close_by_the_ratio_from_the_same_filing(baba):
    # Second review: BABA's close per ADS x ordinary shares gave 8 times the market cap.
    context, shares, ratio = baba
    series = prices(context, "prices-baba", [{"date": "2026-10-30", "close": 160.0, "adj_close": 160.0}])
    cap = calc(context, "market_cap", prices=series, shares=shares["id"], ads_ratio=ratio["id"])
    assert cap.status == "ok" and cap.data["value"] == str(Decimal(160) / 8 * 18580374278)
    assert cap.data["inputs"]["ads_ratio"] == ratio["id"]
    assert "/ 8 ordinary shares per listed share" in cap.data["notes"][0] and ratio["accession"] in cap.data["notes"][0]
    assert not cap.warnings
    # Rechecked offline from the frozen inputs alone, as evidence.recheck does.
    frozen = type(context)(cutoff=context.cutoff, sec=None, records={i: context.records[i] for i in cap.data["inputs"].values()})
    assert run(CalculateInput(formula="market_cap", inputs=cap.data["inputs"]), frozen).data["value"] == cap.data["value"]


def test_ads_market_cap_without_the_ratio_says_to_pass_it(baba):
    context, shares, _ = baba
    series = prices(context, "prices-baba", [{"date": "2026-10-30", "close": 160.0, "adj_close": 160.0}])
    cap = calc(context, "market_cap", prices=series, shares=shares["id"])
    assert cap.status == "unsupported" and "pass ads_ratio" in cap.data["reason"] and shares["accession"] in cap.data["reason"]


def test_ads_ratio_from_another_filing_is_rejected(baba):
    context, shares, ratio = baba
    context.remember({**ratio, "kind": "fact", "metric": "ordinary_shares_per_ads", "id": "fact-old-ratio",
                      "accession": "0000950170-25-090161"})
    series = prices(context, "prices-baba", [{"date": "2026-10-30", "close": 160.0, "adj_close": 160.0}])
    cap = calc(context, "market_cap", prices=series, shares=shares["id"], ads_ratio="fact-old-ratio")
    assert cap.status == "invalid" and "share count's filing" in cap.warnings[0]


def test_ads_ratio_must_be_the_ratio_fact(baba):
    context, shares, _ = baba
    series = prices(context, "prices-baba", [{"date": "2026-10-30", "close": 160.0, "adj_close": 160.0}])
    cap = calc(context, "market_cap", prices=series, shares=shares["id"], ads_ratio=shares["id"])
    assert cap.status == "invalid" and "not get_financials' ordinary_shares_per_ads" in cap.warnings[0]


def test_ads_market_cap_warns_when_the_filing_is_over_a_year_older_than_the_price(baba):
    context, shares, ratio = baba
    series = prices(context, "prices-baba", [{"date": "2027-06-01", "close": 160.0, "adj_close": 160.0}])
    cap = calc(context, "market_cap", prices=series, shares=shares["id"], ads_ratio=ratio["id"])
    assert cap.status == "ok" and any("more than a year before the price" in w for w in cap.warnings)


def test_a_direct_listing_uses_its_ratio_of_one(tmp_path):
    context = make_context(tmp_path)
    result = get_financials(GetFinancialsInput(cik="1015922", years=1, metrics=["shares_outstanding"]), context)
    shares = result.data["metrics"]["shares_outstanding"]["values"][0]
    ratio = result.data["metrics"]["ordinary_shares_per_ads"]["values"][0]
    series = prices(context, "prices-chkp", [{"date": "2026-10-30", "close": 200.0, "adj_close": 200.0}])
    cap = calc(context, "market_cap", prices=series, shares=shares["id"], ads_ratio=ratio["id"])
    assert cap.status == "ok" and cap.data["value"] == str(200 * 105596035)


def test_a_10k_share_count_refuses_an_ads_ratio(apple, baba):
    context, ids = apple
    _, _, ratio = baba
    context.remember(ratio | {"kind": "fact", "metric": "ordinary_shares_per_ads", "cik": "0000320193"})
    series = prices(context, "prices-aapl", [{"date": "2026-10-30", "close": 250.0, "adj_close": 250.0}])
    cap = calc(context, "market_cap", prices=series, shares=ids["2026-07-17", "shares_outstanding"], ads_ratio=ratio["id"])
    assert cap.status == "invalid" and "drop ads_ratio" in cap.warnings[0]


def test_converted_inputs_are_named_and_growth_says_it_includes_currency_moves(tmp_path, monkeypatch):
    monkeypatch.setattr(fx_frankfurter, "transport", httpx.MockTransport(Frankfurter()))
    context = make_context(tmp_path)
    result = get_financials(GetFinancialsInput(cik="1577552", years=2, metrics=["revenue"]), context)
    latest, prior = result.data["metrics"]["revenue"]["values"]
    growth = calc(context, "growth", current=latest["id"], previous=prior["id"])
    assert growth.status == "ok" and any("converted from CNY at 7.200000" in n for n in growth.data["notes"])
    assert any("includes exchange-rate moves" in n for n in growth.data["notes"])
