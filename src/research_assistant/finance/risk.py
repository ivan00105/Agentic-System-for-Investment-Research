"""Price-based risk with the standard library (REFERENCE §10): simple daily returns, annualised with
config.TRADING_DAYS_PER_YEAR. Inputs are adjusted closes in date order."""
import math
import statistics

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
