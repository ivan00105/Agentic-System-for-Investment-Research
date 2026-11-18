from decimal import Decimal
from datetime import date, timedelta

import pytest

from research_assistant.finance import fundamentals, quant, risk


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


def test_risk_forecast_uses_forward_returns_and_requires_enough_history():
    stock = [100 + index * 0.2 for index in range(80)]
    benchmark = [100 + index * 0.1 for index in range(80)]
    result = risk.forecast(
        stock, benchmark, 5, periods_per_year=252, quantile_low=0.1, quantile_high=0.9,
        trailing_threshold=-0.1, har_week_days=5, har_month_days=22, conformal_coverage=0.8,
        conformal_learning_rate=0.01, min_observations=60,
    )
    assert result.value.observations == 75
    assert result.value.own_low < result.value.own_high
    assert result.value.trail_probability == 0
    assert result.value.own_conformal_scale > 0

    insufficient = risk.forecast(
        stock[:20], benchmark[:20], 5, periods_per_year=252, quantile_low=0.1, quantile_high=0.9,
        trailing_threshold=-0.1, har_week_days=5, har_month_days=22, conformal_coverage=0.8,
        conformal_learning_rate=0.01, min_observations=60,
    )
    assert insufficient.value is None and "60" in insufficient.reason


def test_walk_forward_coverage_only_scores_years_after_training_history():
    dates = [(date(2018, 1, 1) + timedelta(days=index)).isoformat() for index in range(1500)]
    stock = [100.0 + index * 0.02 for index in range(len(dates))]
    benchmark = [100.0 + index * 0.01 for index in range(len(dates))]
    result = risk.walk_forward_coverage(
        dates, stock, benchmark, 5, quantile_low=0.1, quantile_high=0.9,
        conformal_coverage=0.8, conformal_learning_rate=0.01,
        min_training_observations=60,
    )
    assert result.value.observations > 0
    assert set(result.value.by_year) == {"2019", "2020", "2021", "2022"}
    assert 0 <= result.value.coverage <= 1
    assert result.value.interval_score >= 0


def test_earnings_window_widens_intervals_by_historical_jump():
    dates = [f"2020-01-{index + 1:02d}" for index in range(10)]
    stock = [100.0, 110.0, 100.0, 100.0, 100.0, 100.0, 100.0, 100.0, 100.0, 100.0]
    benchmark = [100.0] * len(stock)
    common = dict(
        periods_per_year=252, quantile_low=0.1, quantile_high=0.9, trailing_threshold=-0.1,
        har_week_days=2, har_month_days=3, conformal_coverage=0.8,
        conformal_learning_rate=0.01, min_observations=1, session_dates=dates,
        earnings_dates={"2020-01-02"},
    )
    ordinary = risk.forecast(stock, benchmark, 1, **common)
    adjusted = risk.forecast(stock, benchmark, 1, **common, earnings_in_window=True)
    assert adjusted.value.earnings_jump == pytest.approx(0.1)
    assert adjusted.value.earnings_in_window
    assert adjusted.value.own_high - adjusted.value.own_low > ordinary.value.own_high - ordinary.value.own_low


def test_direction_logistic_is_regularised_and_reports_no_unproven_edge():
    stock = [100.0 + index * 0.25 for index in range(400)]
    benchmark = [100.0 + index * 0.20 for index in range(400)]
    result = quant.direction_forecast(
        stock, benchmark, 20, min_observations=252,
        regularization=0.01, learning_rate=0.05, max_iterations=100,
    )
    assert result.value is not None
    assert 0 <= result.value.probability <= 1
    assert result.value.observations >= 252
    assert isinstance(result.value.reliable_edge, bool)


def test_factor_exposure_and_shortlist_are_pure():
    stock = [0.01, -0.02, 0.03, 0.01, -0.01]
    factors = {"MKT": [0.02, -0.01, 0.02, 0.01, -0.02],
               "SMB": [0.01, 0.01, -0.01, 0.02, 0.01]}
    exposure = quant.factor_exposure(stock, factors, ("MKT", "SMB"))
    assert exposure.value is not None
    assert set(exposure.value.betas) == {"MKT", "SMB"}

    aligned = {
        "A": {f"d{i}": 100 * (1.001 ** i) for i in range(30)},
        "B": {f"d{i}": 100 * (1.002 ** i) for i in range(30)},
    }
    shortlist = quant.shortlist_risk(aligned, None, 252)
    assert shortlist.value is not None
    assert shortlist.value.equal_weight_volatility >= 0
    assert len(shortlist.value.correlations) == 1


def test_strategy_summary_has_drawdown_and_losing_year_count():
    dates = [f"{year}-01-01" for year in range(2018, 2022)]
    returns = [0.1, -0.2, 0.05, 0.08]
    result = quant.strategy_stats("value", dates, returns, 252)
    assert result.value is not None
    assert result.value.worst_drawdown < 0
    assert result.value.losing_years == 1
