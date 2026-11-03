from decimal import Decimal

import pytest

from research_assistant.finance import fundamentals, risk


def test_ratio_guards_zero_and_negative_denominators():
    assert fundamentals.ratio(Decimal(1), Decimal(4)).value == Decimal("0.25")
    for denominator in (Decimal(0), Decimal(-5)):
        outcome = fundamentals.ratio(Decimal(1), denominator)
        assert outcome.value is None and "zero or negative" in outcome.reason


def test_growth_and_its_negative_base():
    assert fundamentals.growth(Decimal(120), Decimal(100)).value == Decimal("0.2")
    assert fundamentals.growth(Decimal(5), Decimal(-10)).value is None


def test_margin_change_is_in_percentage_points():
    assert fundamentals.change_pp(Decimal("0.12"), Decimal("0.10")).value == Decimal("2.00")


def test_cagr():
    assert fundamentals.cagr(Decimal(100), Decimal(121), Decimal(2)).value == pytest.approx(Decimal("0.1"))
    assert fundamentals.cagr(Decimal(-1), Decimal(121), Decimal(2)).value is None


def test_free_cash_flow_treats_capex_as_spent_whatever_its_sign():
    assert fundamentals.free_cash_flow(Decimal(100), Decimal(30)).value == Decimal(70)
    negative = fundamentals.free_cash_flow(Decimal(100), Decimal(-30))
    assert negative.value == Decimal(70) and "negative" in negative.note


def test_pe_not_meaningful_with_losses():
    assert fundamentals.multiple(Decimal(1000), Decimal(-1), "PE").value is None


def test_risk_measures():
    closes = [100.0, 110.0, 99.0, 108.9]
    assert risk.total_return(closes).value == pytest.approx(0.089)
    assert risk.max_drawdown(closes).value == pytest.approx(-0.1)
    assert risk.volatility(closes, 252).value > 0
    assert risk.volatility(closes[:2], 252).value is None


def test_beta_of_a_stock_moving_twice_the_benchmark():
    bench = {"d1": 100.0, "d2": 101.0, "d3": 100.0, "d4": 102.0}
    stock = {"d0": 50.0, "d1": 100.0, "d2": 102.0, "d3": 99.980198, "d4": 103.979406}
    outcome = risk.beta(stock, bench)
    assert outcome.value == pytest.approx(2.0, rel=1e-3) and "4 shared trading days" in outcome.note
