from decimal import Decimal

import pytest
from sec_files import make_context

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
