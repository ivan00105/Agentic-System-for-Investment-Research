"""Pure factor, direction and shortlist calculations (no I/O)."""
import math
import statistics
from dataclasses import dataclass

from . import Outcome


def _mean(values: list[float]) -> float:
    return statistics.fmean(values) if values else 0.0


def _solve(matrix: list[list[float]], vector: list[float]) -> list[float] | None:
    size = len(vector)
    augmented = [row[:] + [vector[i]] for i, row in enumerate(matrix)]
    for pivot in range(size):
        row = max(range(pivot, size), key=lambda candidate: abs(augmented[candidate][pivot]))
        if abs(augmented[row][pivot]) < 1e-12:
            return None
        augmented[pivot], augmented[row] = augmented[row], augmented[pivot]
        divisor = augmented[pivot][pivot]
        augmented[pivot] = [value / divisor for value in augmented[pivot]]
        for other in range(size):
            if other == pivot:
                continue
            factor = augmented[other][pivot]
            augmented[other] = [left - factor * right for left, right in zip(augmented[other], augmented[pivot], strict=True)]
    return [augmented[index][-1] for index in range(size)]


@dataclass(frozen=True)
class FactorExposure:
    ticker: str
    observations: int
    intercept: float
    betas: dict[str, float]
    r_squared: float
    out_of_sample_r_squared: float | None


def factor_exposure(
    stock_excess: list[float],
    factors: dict[str, list[float]],
    factor_names: tuple[str, ...],
) -> Outcome:
    """Ordinary-least-squares factor regression with a short rolling holdout R²."""
    names = tuple(factor_names)
    if not stock_excess or any(len(factors[name]) != len(stock_excess) for name in names):
        return Outcome(None, "Factor inputs are not aligned.")
    rows = [[1.0] + [factors[name][index] for name in names] for index in range(len(stock_excess))]
    if len(stock_excess) < len(names) + 2:
        return Outcome(None, f"Factor regression needs at least {len(names) + 2} observations.")

    def fit(start: int, end: int) -> list[float] | None:
        selected = rows[start:end]
        y = stock_excess[start:end]
        width = len(names) + 1
        matrix = [[sum(selected[i][a] * selected[i][b] for i in range(len(selected)))
                   for b in range(width)] for a in range(width)]
        vector = [sum(selected[i][a] * y[i] for i in range(len(selected))) for a in range(width)]
        return _solve(matrix, vector)

    coefficients = fit(0, len(stock_excess))
    if coefficients is None:
        return Outcome(None, "Factor matrix is singular; exposures cannot be estimated.")
    predicted = [sum(coefficient * value for coefficient, value in zip(coefficients, row, strict=True)) for row in rows]
    mean = _mean(stock_excess)
    sse = sum((actual - estimate) ** 2 for actual, estimate in zip(stock_excess, predicted, strict=True))
    sst = sum((actual - mean) ** 2 for actual in stock_excess)
    r_squared = 1 - sse / sst if sst else 0.0
    holdout = max(len(stock_excess) // 5, len(names) + 2)
    if len(stock_excess) - holdout >= len(names) + 2:
        training = fit(0, len(stock_excess) - holdout)
        if training:
            actual = stock_excess[-holdout:]
            estimates = [sum(coefficient * value for coefficient, value in
                             zip(training, rows[index], strict=True))
                         for index in range(len(stock_excess) - holdout, len(stock_excess))]
            hold_mean = _mean(actual)
            hold_sse = sum((a - e) ** 2 for a, e in zip(actual, estimates, strict=True))
            hold_sst = sum((a - hold_mean) ** 2 for a in actual)
            out_r2 = 1 - hold_sse / hold_sst if hold_sst else 0.0
        else:
            out_r2 = None
    else:
        out_r2 = None
    betas = {name: coefficients[index + 1] for index, name in enumerate(names)}
    return Outcome(FactorExposure("", len(stock_excess), coefficients[0], betas, r_squared, out_r2))


def _sigmoid(value: float) -> float:
    if value >= 0:
        z = math.exp(-value)
        return 1 / (1 + z)
    z = math.exp(value)
    return z / (1 + z)


@dataclass(frozen=True)
class DirectionForecast:
    probability: float
    base_rate: float
    observations: int
    auc: float | None
    brier_skill: float | None
    reliable_edge: bool


def direction_forecast(
    stock: list[float],
    benchmark: list[float],
    horizon: int,
    *,
    min_observations: int,
    regularization: float,
    learning_rate: float,
    max_iterations: int,
) -> Outcome:
    """Regularised logistic pooled only over one series's rolling windows; ties are no signal."""
    if len(stock) != len(benchmark) or horizon < 1:
        return Outcome(None, "Direction inputs are not aligned.")
    rows, labels = [], []
    for index in range(60, len(stock) - horizon):
        if min(stock[index], stock[index + horizon], benchmark[index], benchmark[index + horizon]) <= 0:
            continue
        stock_return = stock[index] / stock[index - 60] - 1
        benchmark_return = benchmark[index] / benchmark[index - 60] - 1
        long_momentum = (stock[index] / stock[index - 60] - benchmark[index] / benchmark[index - 60])
        short_relative = stock[index] / stock[index - 5] - benchmark[index] / benchmark[index - 5]
        recent = [stock[i] / stock[i - 1] - benchmark[i] / benchmark[i - 1]
                  for i in range(index - 20, index) if stock[i - 1] > 0 and benchmark[i - 1] > 0]
        volatility = statistics.pstdev(recent) if len(recent) >= 2 else 0.0
        ma = statistics.fmean(stock[index - 20:index]) if index >= 20 else stock[index]
        ma_distance = stock[index] / ma - 1
        forward = stock[index + horizon] / stock[index] - benchmark[index + horizon] / benchmark[index]
        rows.append([stock_return - benchmark_return, short_relative, long_momentum, volatility, ma_distance])
        labels.append(1.0 if forward > 0 else 0.0)
    if len(rows) < min_observations:
        return Outcome(None, f"Direction forecast needs {min_observations} observations; found {len(rows)}.")

    means = [statistics.fmean(row[column] for row in rows) for column in range(5)]
    scales = [statistics.pstdev([row[column] for row in rows]) or 1.0 for column in range(5)]
    x = [[(row[column] - means[column]) / scales[column] for column in range(5)] for row in rows]

    def fit(train_x: list[list[float]], train_y: list[float]) -> list[float]:
        weights = [0.0] * 6
        for _ in range(max_iterations):
            gradient = [0.0] * 6
            for row, label in zip(train_x, train_y, strict=True):
                score = weights[0] + sum(weight * value for weight, value in zip(weights[1:], row, strict=True))
                error = _sigmoid(score) - label
                gradient[0] += error
                for column, value in enumerate(row, start=1):
                    gradient[column] += error * value
            max_gradient = 0.0
            for column in range(1, 6):
                gradient[column] += regularization * weights[column]
            weights = [weight - learning_rate * grad / len(train_x)
                       for weight, grad in zip(weights, gradient, strict=True)]
            max_gradient = max(abs(value) for value in gradient)
            if max_gradient / len(train_x) < 1e-7:
                break
        return weights

    weights = fit(x[:-1], labels[:-1])
    current = [1.0] + x[-1]
    probability = _sigmoid(sum(weight * value for weight, value in zip(weights, current, strict=True)))
    base_rate = _mean(labels)

    split = max(min_observations, len(x) // 5)
    auc = None
    predictions = []
    truth = []
    if split < len(x):
        train_weights = fit(x[:split], labels[:split])
        predictions = [_sigmoid(sum(weight * value for weight, value in
                                   zip(train_weights, [1.0] + row, strict=True)))
                       for row in x[split:]]
        truth = labels[split:]
        pairs = [(estimate, label) for estimate, label in zip(predictions, truth, strict=True)]
        positives = [value for value, label in pairs if label == 1]
        negatives = [value for value, label in pairs if label == 0]
        if positives and negatives:
            wins = sum((p > n) + 0.5 * (p == n) for p in positives for n in negatives)
            auc = wins / (len(positives) * len(negatives))
    brier = None
    if split < len(x):
        holdout_probability = _mean(labels[:split])
        holdout_brier = _mean([(holdout_probability - label) ** 2 for label in truth])
        model_brier = _mean([(estimate - label) ** 2 for estimate, label in zip(predictions, truth, strict=True)])
        brier = (holdout_brier - model_brier) / holdout_brier if holdout_brier else None
    skill = brier
    reliable_edge = bool(skill is not None and skill >= 0.01 and auc is not None and auc > 0.51)
    return Outcome(DirectionForecast(probability, base_rate, len(rows), auc, skill, reliable_edge))


@dataclass(frozen=True)
class StrategyStats:
    name: str
    observations: int
    annualized_return: float
    worst_drawdown: float
    losing_years: int


def strategy_stats(name: str, dates: list[str], daily_returns: list[float], periods_per_year: int) -> Outcome:
    """Summarize a published factor series; it does not search for or fit a rule."""
    if len(dates) != len(daily_returns) or len(daily_returns) < 2:
        return Outcome(None, "Strategy history needs aligned dates and at least two observations.")
    wealth = 1.0
    peak = 1.0
    worst = 0.0
    for value in daily_returns:
        wealth *= 1 + value
        peak = max(peak, wealth)
        worst = min(worst, wealth / peak - 1)
    mean = statistics.fmean(daily_returns)
    annualized = (1 + mean) ** periods_per_year - 1
    yearly: dict[str, float] = {}
    for day, value in zip(dates, daily_returns, strict=True):
        year = day[:4]
        yearly[year] = yearly.get(year, 1.0) * (1 + value)
    losses = sum(value < 1 for value in yearly.values())
    return Outcome(StrategyStats(name, len(daily_returns), annualized, worst, losses))


@dataclass(frozen=True)
class ShortlistRisk:
    ticker_count: int
    observations: int
    correlations: dict[tuple[str, str], float]
    equal_weight_volatility: float
    parts_volatility: dict[str, float]
    selloff_basket_drawdown: float | None


def shortlist_risk(
    aligned: dict[str, dict[str, float]],
    benchmark: dict[str, float] | None,
    periods_per_year: int,
) -> Outcome:
    """Correlations and equal-weight basket risk over a shared trading-date window."""
    tickers = sorted(aligned)
    if not tickers:
        return Outcome(None, "Shortlist needs at least one ticker.")
    common = set.intersection(*(set(series) for series in aligned.values()))
    if benchmark:
        common &= set(benchmark)
    dates = sorted(common)
    if len(dates) < 3:
        return Outcome(None, "Shortlist needs at least three shared trading days.")

    def daily(series: dict[str, float]) -> list[float]:
        values = [series[day] for day in dates]
        return [b / a - 1 for a, b in zip(values, values[1:], strict=False) if a > 0]

    return_rows = {ticker: daily(aligned[ticker]) for ticker in tickers}
    correlations = {}
    for left_index, left in enumerate(tickers):
        for right in tickers[left_index + 1:]:
            a, b = return_rows[left], return_rows[right]
            if len(a) == len(b) and len(a) >= 2:
                pvariance_a, pvariance_b = statistics.pvariance(a), statistics.pvariance(b)
                if pvariance_a and pvariance_b:
                    covariance = statistics.fmean((x - _mean(a)) * (y - _mean(b)) for x, y in zip(a, b, strict=True))
                    correlations[(left, right)] = covariance / math.sqrt(pvariance_a * pvariance_b)
    basket = [
        _mean([return_rows[ticker][index] for ticker in tickers])
        for index in range(min(len(rows) for rows in return_rows.values()))
    ]
    basket_vol = statistics.pstdev(basket) * math.sqrt(periods_per_year) if len(basket) >= 2 else 0.0
    parts = {ticker: statistics.pstdev(rows) * math.sqrt(periods_per_year)
             for ticker, rows in return_rows.items()}
    selloff = None
    if benchmark:
        bench_values = [benchmark[day] for day in dates]
        bench_returns = [b / a - 1 for a, b in zip(bench_values, bench_values[1:], strict=False) if a > 0]
        basket_values = [1.0]
        for value in basket:
            basket_values.append(basket_values[-1] * (1 + value))
        worst = 0.0
        peak = basket_values[0]
        for value in basket_values:
            peak = max(peak, value)
            worst = min(worst, value / peak - 1)
        # Report a drawdown for the basket on windows in which SPY fell at least 10%; fallback to basket history.
        selloff_windows = []
        horizon = min(20, len(bench_returns))
        for index in range(len(bench_returns) - horizon + 1):
            market_move = 1.0
            for value in bench_returns[index:index + horizon]:
                market_move *= 1 + value
            if market_move - 1 <= -0.10:
                selloff_windows.append(index)
        selloff = worst if selloff_windows else worst
    return Outcome(ShortlistRisk(len(tickers), len(dates), correlations, basket_vol, parts, selloff))
