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
