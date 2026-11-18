"""Price-based risk with the standard library (REFERENCE §10): simple daily returns, annualised with
config.TRADING_DAYS_PER_YEAR. Inputs are adjusted closes in date order."""
import math
import statistics
from dataclasses import dataclass

from . import Outcome


def returns(closes: list[float]) -> list[float]:
    return [b / a - 1 for a, b in zip(closes, closes[1:], strict=False) if a > 0]


def total_return(closes: list[float]) -> Outcome:
    if len(closes) < 2 or closes[0] <= 0:
        return Outcome(None, "Total return needs at least two prices and a positive first price.")
    return Outcome(closes[-1] / closes[0] - 1)


def volatility(closes: list[float], periods_per_year: int) -> Outcome:
    daily = returns(closes)
    if len(daily) < 2:
        return Outcome(None, "Volatility needs at least three prices.")
    return Outcome(statistics.stdev(daily) * math.sqrt(periods_per_year))


def max_drawdown(closes: list[float]) -> Outcome:
    if not closes:
        return Outcome(None, "Drawdown needs prices.")
    peak, worst = closes[0], 0.0
    for close in closes:
        peak = max(peak, close)
        worst = min(worst, close / peak - 1)
    return Outcome(worst)


def sharpe(closes: list[float], risk_free: float, periods_per_year: int) -> Outcome:
    """(Annualised mean daily return - the risk-free rate) / annualised volatility, as in Sharpe (1994)."""
    daily = returns(closes)
    if len(daily) < 2:
        return Outcome(None, "A Sharpe ratio needs at least three prices.")
    spread = statistics.stdev(daily)
    if spread == 0:
        return Outcome(None, "A Sharpe ratio is undefined when the price never moves.")
    excess = statistics.fmean(daily) * periods_per_year - risk_free
    return Outcome(excess / (spread * math.sqrt(periods_per_year)),
                   note=f"Mean daily return x {periods_per_year} minus the risk-free rate {risk_free:.4%}, over "
                        f"volatility; {len(daily)} daily returns.")


def relative_return(stock: dict[str, float], benchmark: dict[str, float]) -> Outcome:
    """The stock's total return minus the benchmark's, in percentage points, over the dates both have prices."""
    dates = sorted(stock.keys() & benchmark.keys())
    if len(dates) < 2 or stock[dates[0]] <= 0 or benchmark[dates[0]] <= 0:
        return Outcome(None, "A relative return needs two shared trading days with positive prices.")
    own, other = (series[dates[-1]] / series[dates[0]] - 1 for series in (stock, benchmark))
    return Outcome((own - other) * 100, note=f"Total returns {own:.2%} against {other:.2%}, {dates[0]} to {dates[-1]}.")


def beta(stock: dict[str, float], benchmark: dict[str, float]) -> Outcome:
    """Slope of the stock's daily returns on the benchmark's, over the dates both have prices."""
    dates = sorted(stock.keys() & benchmark.keys())
    stock_returns, bench_returns = returns([stock[d] for d in dates]), returns([benchmark[d] for d in dates])
    if len(dates) < 3 or len(stock_returns) != len(bench_returns):
        return Outcome(None, "Beta needs at least three shared trading days with positive prices.")
    if statistics.pvariance(bench_returns) == 0:
        return Outcome(None, "Beta is undefined when the benchmark never moves.")
    return Outcome(statistics.linear_regression(bench_returns, stock_returns).slope,
                   note=f"Over {len(dates)} shared trading days, {dates[0]} to {dates[-1]}.")


@dataclass(frozen=True)
class RiskForecast:
    """Empirical forward-return statistics used by the host-owned outlook tool."""

    observations: int
    own_low: float
    own_high: float
    relative_low: float
    relative_high: float
    own_conformal_scale: float
    relative_conformal_scale: float
    trail_probability: float
    har_annualized_volatility: float | None
    down_beta: float | None
    worst_selloff_relative_return: float | None
    earnings_jump: float | None
    earnings_in_window: bool


def _earnings_jump(closes: list[float], dates: list[str], earnings_dates: set[str]) -> float | None:
    jumps = []
    for index, day in enumerate(dates):
        if day in earnings_dates and index > 0 and closes[index - 1] > 0 and closes[index] > 0:
            jumps.append(abs(closes[index] / closes[index - 1] - 1))
    return statistics.median(jumps) if jumps else None


@dataclass(frozen=True)
class WalkForwardCoverage:
    """Out-of-sample coverage diagnostics for a forecast interval."""

    observations: int
    covered: int
    coverage: float
    interval_score: float
    by_year: dict[str, tuple[int, int, float]]


def _quantile(values: list[float], probability: float) -> float:
    if not values:
        raise ValueError("A quantile needs at least one observation.")
    ordered = sorted(values)
    position = (len(ordered) - 1) * probability
    lower, upper = math.floor(position), math.ceil(position)
    if lower == upper:
        return ordered[lower]
    fraction = position - lower
    return ordered[lower] + (ordered[upper] - ordered[lower]) * fraction


def _forward_returns(closes: list[float], benchmark: list[float], horizon: int) -> tuple[list[float], list[float]]:
    own, relative = [], []
    for index in range(len(closes) - horizon):
        if closes[index] <= 0 or closes[index + horizon] <= 0:
            continue
        if benchmark[index] <= 0 or benchmark[index + horizon] <= 0:
            continue
        stock_return = closes[index + horizon] / closes[index] - 1
        benchmark_return = benchmark[index + horizon] / benchmark[index] - 1
        own.append(stock_return)
        relative.append(stock_return - benchmark_return)
    return own, relative


def _conformal_interval(
    values: list[float],
    low: float,
    high: float,
    *,
    coverage: float,
    learning_rate: float,
) -> tuple[float, float, float]:
    """Adapt an empirical interval's half-width to recent misses, without assuming normal returns."""
    center = _quantile(values, 0.5)
    base_radius = max(center - low, high - center)
    radius = base_radius
    miss_rate = 1 - coverage
    for value in values:
        miss = abs(value - center) > radius
        radius = max(0.0, radius + learning_rate * (float(miss) - miss_rate))
    scale = radius / base_radius if base_radius else 1.0
    return center - radius, center + radius, scale


def _interval_score(actual: float, low: float, high: float, alpha: float) -> float:
    penalty = 2 / alpha
    return high - low + penalty * max(low - actual, 0) + penalty * max(actual - high, 0)


def walk_forward_coverage(
    dates: list[str],
    closes: list[float],
    benchmark: list[float],
    horizon: int,
    *,
    quantile_low: float,
    quantile_high: float,
    conformal_coverage: float,
    conformal_learning_rate: float,
    min_training_observations: int,
) -> Outcome:
    """Evaluate intervals on each calendar year's unseen forward returns."""
    if len(dates) != len(closes) or len(closes) != len(benchmark):
        return Outcome(None, "Walk-forward inputs are not aligned.")
    if horizon < 1 or not (0 < quantile_low < quantile_high < 1):
        return Outcome(None, "Walk-forward horizon and quantiles are invalid.")
    if len(set(dates)) != len(dates) or dates != sorted(dates):
        return Outcome(None, "Walk-forward dates must be unique and sorted.")

    years = sorted({date[:4] for date in dates})
    yearly: dict[str, tuple[int, int, float]] = {}
    scores: list[float] = []
    total, covered = 0, 0
    for year in years:
        test_start = next(index for index, date in enumerate(dates) if date[:4] == year)
        if test_start == 0:
            continue
        training_own, _ = _forward_returns(closes[:test_start], benchmark[:test_start], horizon)
        if len(training_own) < min_training_observations:
            continue
        low, high, _ = _conformal_interval(
            training_own,
            _quantile(training_own, quantile_low),
            _quantile(training_own, quantile_high),
            coverage=conformal_coverage,
            learning_rate=conformal_learning_rate,
        )
        year_total, year_covered = 0, 0
        for index in range(test_start, len(closes) - horizon):
            if min(closes[index], closes[index + horizon], benchmark[index], benchmark[index + horizon]) <= 0:
                continue
            actual = closes[index + horizon] / closes[index] - 1
            year_total += 1
            year_covered += int(low <= actual <= high)
            scores.append(_interval_score(actual, low, high, quantile_high - quantile_low))
        if year_total:
            yearly[year] = (year_total, year_covered, year_covered / year_total)
            total += year_total
            covered += year_covered
    if not total:
        return Outcome(None, "Walk-forward evaluation has no eligible test observations.")
    return Outcome(WalkForwardCoverage(
        observations=total,
        covered=covered,
        coverage=covered / total,
        interval_score=statistics.fmean(scores),
        by_year=yearly,
    ))


def _har_volatility(closes: list[float], periods_per_year: int, week_days: int, month_days: int) -> float | None:
    daily = returns(closes)
    if len(daily) < month_days + 10:
        return None
    squared = [value * value for value in daily]
    x_rows, y_values = [], []
    for index in range(month_days, len(squared)):
        x_rows.append((1.0, statistics.fmean(squared[index - 1:index]),
                       statistics.fmean(squared[index - week_days:index]),
                       statistics.fmean(squared[index - month_days:index])))
        y_values.append(squared[index])
    if len(y_values) < 10:
        return None
    matrix = [[sum(row[column] * row[other] for row in x_rows) for other in range(4)] for column in range(4)]
    vector = [sum(row[column] * value for row, value in zip(x_rows, y_values, strict=True)) for column in range(4)]
    for pivot in range(4):
        row = max(range(pivot, 4), key=lambda candidate: abs(matrix[candidate][pivot]))
        if abs(matrix[row][pivot]) < 1e-14:
            return None
        matrix[pivot], matrix[row] = matrix[row], matrix[pivot]
        vector[pivot], vector[row] = vector[row], vector[pivot]
        divisor = matrix[pivot][pivot]
        matrix[pivot] = [value / divisor for value in matrix[pivot]]
        vector[pivot] /= divisor
        for other in range(4):
            if other == pivot:
                continue
            factor = matrix[other][pivot]
            matrix[other] = [left - factor * right for left, right in zip(matrix[other], matrix[pivot], strict=True)]
            vector[other] -= factor * vector[pivot]
    latest = (1.0, squared[-1], statistics.fmean(squared[-week_days:]), statistics.fmean(squared[-month_days:]))
    forecast_variance = sum(coefficient * component for coefficient, component in zip(vector, latest, strict=True))
    return math.sqrt(max(forecast_variance, 0.0) * periods_per_year)


def _down_beta(stock: list[float], benchmark: list[float]) -> float | None:
    stock_returns, benchmark_returns = [], []
    for own_before, own_after, benchmark_before, benchmark_after in zip(
        stock, stock[1:], benchmark, benchmark[1:], strict=False
    ):
        if min(own_before, own_after, benchmark_before, benchmark_after) <= 0:
            continue
        benchmark_return = benchmark_after / benchmark_before - 1
        if benchmark_return < 0:
            benchmark_returns.append(benchmark_return)
            stock_returns.append(own_after / own_before - 1)
    if len(stock_returns) < 3 or statistics.pvariance(benchmark_returns) == 0:
        return None
    return statistics.linear_regression(benchmark_returns, stock_returns).slope


def _worst_selloff_relative_return(stock: list[float], benchmark: list[float], horizon: int) -> float | None:
    _, relative = _forward_returns(stock, benchmark, horizon)
    selloffs = []
    for index in range(len(benchmark) - horizon):
        if benchmark[index] > 0 and benchmark[index + horizon] > 0:
            market_return = benchmark[index + horizon] / benchmark[index] - 1
            if market_return <= -0.10 and index < len(stock) - horizon and stock[index] > 0 and stock[index + horizon] > 0:
                selloffs.append(stock[index + horizon] / stock[index] - 1 - market_return)
    return min(selloffs) if selloffs else (min(relative) if relative else None)


def forecast(
    closes: list[float],
    benchmark: list[float],
    horizon: int,
    *,
    periods_per_year: int,
    quantile_low: float,
    quantile_high: float,
    trailing_threshold: float,
    har_week_days: int,
    har_month_days: int,
    conformal_coverage: float,
    conformal_learning_rate: float,
    min_observations: int,
    session_dates: list[str] | None = None,
    earnings_dates: set[str] | None = None,
    earnings_in_window: bool = False,
) -> Outcome:
    """Build a conservative empirical risk forecast from aligned adjusted closes."""
    if len(closes) != len(benchmark):
        return Outcome(None, "The stock and benchmark price series are not aligned.")
    own, relative = _forward_returns(closes, benchmark, horizon)
    if len(own) < min_observations:
        return Outcome(None, f"Risk forecast needs {min_observations} forward observations; found {len(own)}.")
    own_low, own_high, own_scale = _conformal_interval(
        own, _quantile(own, quantile_low), _quantile(own, quantile_high),
        coverage=conformal_coverage, learning_rate=conformal_learning_rate,
    )
    relative_low, relative_high, relative_scale = _conformal_interval(
        relative, _quantile(relative, quantile_low), _quantile(relative, quantile_high),
        coverage=conformal_coverage, learning_rate=conformal_learning_rate,
    )
    event_jump = None
    if session_dates is not None and len(session_dates) == len(closes) and earnings_dates:
        event_jump = _earnings_jump(closes, session_dates, earnings_dates)
    if earnings_in_window and event_jump is not None:
        own_center = (own_low + own_high) / 2
        relative_center = (relative_low + relative_high) / 2
        own_radius = (own_high - own_low) / 2 + event_jump
        relative_radius = (relative_high - relative_low) / 2 + event_jump
        own_low, own_high = own_center - own_radius, own_center + own_radius
        relative_low, relative_high = relative_center - relative_radius, relative_center + relative_radius
    return Outcome(RiskForecast(
        observations=len(own),
        own_low=own_low,
        own_high=own_high,
        relative_low=relative_low,
        relative_high=relative_high,
        own_conformal_scale=own_scale,
        relative_conformal_scale=relative_scale,
        trail_probability=sum(value <= trailing_threshold for value in relative) / len(relative),
        har_annualized_volatility=_har_volatility(closes, periods_per_year, har_week_days, har_month_days),
        down_beta=_down_beta(closes, benchmark),
        worst_selloff_relative_return=_worst_selloff_relative_return(closes, benchmark, horizon),
        earnings_jump=event_jump,
        earnings_in_window=earnings_in_window and event_jump is not None,
    ))
