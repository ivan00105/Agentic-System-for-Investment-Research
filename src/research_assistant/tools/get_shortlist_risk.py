"""Shortlist correlation and equal-weight basket risk over shared prices."""
from datetime import date, timedelta

from pydantic import BaseModel, Field

from .. import config
from ..data import prices
from ..finance import quant
from .get_prices import GetPricesInput, run as get_prices
from .result import Tool, ToolContext, ToolResult, make_id


class GetShortlistRiskInput(BaseModel):
    tickers: list[str] = Field(min_length=1, description="Tickers to compare.")
    start: date | None = None
    end: date | None = None


def run(args: GetShortlistRiskInput, context: ToolContext) -> ToolResult:
    tickers = list(dict.fromkeys(ticker.strip().upper() for ticker in args.tickers if ticker.strip()))
    if not tickers:
        return ToolResult(status="invalid", source="shortlist", warnings=["At least one ticker is required."])
    end = args.end or prices.last_known_day(context.cutoff)
    start = args.start or end - timedelta(days=config.PRICE_DEFAULT_LOOKBACK_DAYS)
    aligned, parts = {}, []
    warnings = []
    for ticker in tickers:
        result = get_prices(GetPricesInput(ticker=ticker, start=start, end=end), context)
        if result.status != "ok":
            warnings.append(f"{ticker}: {result.status}: {' '.join(result.warnings)}")
            continue
        record = context.records[result.ids[0]]
        aligned[ticker] = {row["date"]: row["adj_close"] for row in record["rows"]}
        parts.append(record["id"])
    benchmark_result = get_prices(GetPricesInput(ticker="SPY", start=start, end=end), context)
    benchmark = None
    if benchmark_result.status == "ok":
        benchmark_record = context.records[benchmark_result.ids[0]]
        benchmark = {row["date"]: row["adj_close"] for row in benchmark_record["rows"]}
        parts.append(benchmark_record["id"])
    else:
        warnings.append("SPY benchmark unavailable; basket selloff context is omitted.")
    outcome = quant.shortlist_risk(aligned, benchmark, config.TRADING_DAYS_PER_YEAR)
    if outcome.value is None:
        return ToolResult(status="unsupported", source="shortlist",
                          warnings=warnings + [outcome.reason or "Shortlist risk is unavailable."])
    result = outcome.value
    correlations = [{"left": left, "right": right, "correlation": round(correlation, 8)}
                    for (left, right), correlation in sorted(result.correlations.items())]
    prefix = make_id("shortlist", "|".join(sorted(aligned)))
    record = {
        "id": make_id(prefix, start.isoformat(), end.isoformat(), result.observations),
        "kind": "calc", "formula": "shortlist_risk", "ticker": None,
        "value": result.equal_weight_volatility, "unit": "ratio",
        "start": start.isoformat(), "end": end.isoformat(),
        "inputs": {"price_series": parts, "benchmark": "SPY" if benchmark else None},
        "status": "ok", "ticker_count": result.ticker_count, "observations": result.observations,
        "correlations": correlations, "equal_weight_volatility": result.equal_weight_volatility,
        "parts_volatility": result.parts_volatility,
        "selloff_basket_drawdown": result.selloff_basket_drawdown,
        "method": "Equal-weight basket: 1/N each, using only the shared adjusted-close window.",
    }
    context.remember(record)
    status = "ok" if len(aligned) == len(tickers) else "partial"
    return ToolResult(status=status, data={**record, "id": record["id"]}, ids=[record["id"]],
                      source="adjusted prices", warnings=warnings)


TOOL = Tool("get_shortlist_risk",
            "Measure pair correlations and equal-weight basket volatility for a shortlist; no portfolio weights are optimised.",
            GetShortlistRiskInput, run, "shortlist")
