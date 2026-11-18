"""Host-owned empirical risk outlook from adjusted stock and SPY closes."""
from datetime import date, timedelta, datetime, timezone

import exchange_calendars as xcals
from pydantic import BaseModel, Field

from .. import config
from ..data import prices
from ..data import sec_filings
from ..finance import quant, risk
from .get_prices import GetPricesInput, run as get_prices
from .result import Tool, ToolContext, ToolResult, make_id


class GetOutlookInput(BaseModel):
    ticker: str = Field(min_length=1, max_length=12, description="Stock ticker, e.g. AAPL.")
    start: date | None = Field(None, description="First day of history; defaults to the configured risk lookback.")
    end: date | None = Field(None, description="Last day; defaults and is capped at the research cutoff.")
    horizons: list[int] = Field(
        default_factory=lambda: [5, 20],
        min_length=1,
        description="Forward trading-session horizons. The default is 5 and 20.",
    )
    earnings_date: date | None = Field(
        None, description="Optional next earnings date; used to widen the range if it falls inside the horizon."
    )


def _aligned_rows(stock: dict, benchmark: dict, start: date, end: date) -> tuple[list[str], list[float], list[float]]:
    stock_rows = {row["date"]: row["adj_close"] for row in stock["rows"]}
    benchmark_rows = {row["date"]: row["adj_close"] for row in benchmark["rows"]}
    sessions = {
        timestamp.date().isoformat()
        for timestamp in xcals.get_calendar("XNYS").sessions_in_range(start.isoformat(), end.isoformat())
    }
    dates = sorted(stock_rows.keys() & benchmark_rows.keys() & sessions)
    return dates, [stock_rows[day] for day in dates], [benchmark_rows[day] for day in dates]


def _historical_earnings_dates(record: dict, context: ToolContext, start: date) -> set[str]:
    cik = record.get("cik")
    if not cik:
        return set()
    filings = sec_filings.search(context.sec, cik, context.cutoff, forms={"8-K"}, since=start)
    return {filing.filed.isoformat() for filing in filings if "2.02" in filing.items}


def _earnings_in_window(last_date: str, earnings_date: date | None, horizon: int) -> bool:
    if earnings_date is None:
        return False
    sessions = xcals.get_calendar("XNYS").sessions_in_range(
        (date.fromisoformat(last_date) + timedelta(days=1)).isoformat(),
        (date.fromisoformat(last_date) + timedelta(days=max(30, horizon * 4))).isoformat(),
    )
    return earnings_date.isoformat() in {timestamp.date().isoformat() for timestamp in sessions[:horizon]}


def run(args: GetOutlookInput, context: ToolContext) -> ToolResult:
    if any(horizon < 1 for horizon in args.horizons):
        return ToolResult(status="invalid", source="outlook",
                          warnings=["Horizons must be positive trading-session counts."])
    end = args.end or prices.last_known_day(context.cutoff)
    start = args.start or end - timedelta(days=config.OUTLOOK_DEFAULT_LOOKBACK_DAYS)
    if start > end:
        return ToolResult(status="invalid", source="outlook", warnings=[f"Start {start} is after end {end}."])

    stock_result = get_prices(GetPricesInput(ticker=args.ticker, start=start, end=end), context)
    if stock_result.status != "ok":
        return ToolResult(status=stock_result.status, source=stock_result.source, warnings=stock_result.warnings)
    benchmark_result = get_prices(GetPricesInput(ticker="SPY", start=start, end=end), context)
    if benchmark_result.status != "ok":
        return ToolResult(status=benchmark_result.status, source=benchmark_result.source,
                          warnings=benchmark_result.warnings + ["SPY is required for relative risk."])
    stock_record = context.records[stock_result.ids[0]]
    benchmark_record = context.records[benchmark_result.ids[0]]
    if stock_record["source"] != benchmark_record["source"]:
        return ToolResult(status="unavailable", source="outlook",
                          warnings=["Stock and SPY prices came from different providers; relative risk was not computed."])
    dates, closes, benchmark = _aligned_rows(stock_record, benchmark_record, start, end)
    if not dates:
        return ToolResult(status="not_found", source="outlook", warnings=["No shared stock and SPY trading days."])

    warnings = stock_result.warnings + benchmark_result.warnings
    earnings_dates = _historical_earnings_dates(stock_record, context, start)
    records, summaries = [], {}
    for horizon in sorted(set(args.horizons)):
        outcome = risk.forecast(
            closes,
            benchmark,
            horizon,
            periods_per_year=config.TRADING_DAYS_PER_YEAR,
            quantile_low=config.OUTLOOK_QUANTILE_LOW,
            quantile_high=config.OUTLOOK_QUANTILE_HIGH,
            trailing_threshold=config.OUTLOOK_TRAILING_THRESHOLD,
            har_week_days=config.OUTLOOK_HAR_WEEK_DAYS,
            har_month_days=config.OUTLOOK_HAR_MONTH_DAYS,
            conformal_coverage=config.OUTLOOK_CONFORMAL_COVERAGE,
            conformal_learning_rate=config.OUTLOOK_CONFORMAL_LEARNING_RATE,
            min_observations=config.OUTLOOK_MIN_OBSERVATIONS,
            session_dates=dates,
            earnings_dates=earnings_dates,
            earnings_in_window=_earnings_in_window(dates[-1], args.earnings_date, horizon),
        )
        if outcome.value is None:
            warnings.append(f"{horizon}-session outlook unavailable: {outcome.reason}")
            continue
        result = outcome.value
        prefix = make_id("outlook", stock_record["id"], benchmark_record["id"], horizon)
        metrics = {
            "own_return_low": (result.own_low, "ratio"),
            "own_return_high": (result.own_high, "ratio"),
            "relative_return_low": (result.relative_low, "ratio"),
            "relative_return_high": (result.relative_high, "ratio"),
            "own_conformal_scale": (result.own_conformal_scale, "ratio"),
            "relative_conformal_scale": (result.relative_conformal_scale, "ratio"),
            "earnings_jump": (result.earnings_jump, "ratio"),
            "trail_spy_probability": (result.trail_probability, "ratio"),
            "har_annualized_volatility": (result.har_annualized_volatility, "ratio"),
            "down_beta": (result.down_beta, "x"),
            "worst_selloff_relative_return": (result.worst_selloff_relative_return, "ratio"),
        }
        horizon_records = []
        for metric, (value, unit) in metrics.items():
            if value is None:
                continue
            record = {
                "id": make_id(prefix, metric), "kind": "calc", "formula": f"outlook_{metric}",
                "ticker": stock_record["ticker"], "cik": stock_record.get("cik"), "value": round(value, 8),
                "unit": unit, "start": dates[0], "end": dates[-1],
                "issued_at": datetime.now(timezone.utc).isoformat(),
                "inputs": {
                    "prices": stock_record["id"], "benchmark": benchmark_record["id"], "horizon": horizon,
                    "sessions": dates,
                    "earnings_dates": sorted(earnings_dates),
                    "earnings_in_window": result.earnings_in_window,
                },
                "status": "ok", "notes": [f"{result.observations} rolling {horizon}-session observations; "
                                            f"80% empirical interval uses the stock's own historical moves with "
                                            f"adaptive conformal calibration."
                                            + (" Earnings-window jump adjustment applied."
                                               if result.earnings_in_window else "")],
            }
            context.remember(record)
            horizon_records.append(record)
        records.extend(horizon_records)
        summaries[str(horizon)] = {"observations": result.observations, "records": [r["id"] for r in horizon_records]}

        direction = quant.direction_forecast(
            closes, benchmark, horizon,
            min_observations=config.DIRECTION_MIN_OBSERVATIONS,
            regularization=config.DIRECTION_REGULARIZATION,
            learning_rate=config.DIRECTION_LEARNING_RATE,
            max_iterations=config.DIRECTION_MAX_ITERATIONS,
        )
        if direction.value is not None:
            direction_result = direction.value
            direction_metrics = {
                "direction_probability": (direction_result.probability, "ratio"),
                "direction_base_rate": (direction_result.base_rate, "ratio"),
                "direction_observations": (float(direction_result.observations), "count"),
            }
            if direction_result.auc is not None:
                direction_metrics["direction_auc"] = (direction_result.auc, "ratio")
            if direction_result.brier_skill is not None:
                direction_metrics["direction_brier_skill"] = (direction_result.brier_skill, "ratio")
            prefix = make_id("outlook-direction", stock_record["id"], benchmark_record["id"], horizon)
            for metric, (value, unit) in direction_metrics.items():
                record = {
                    "id": make_id(prefix, metric), "kind": "calc", "formula": f"outlook_{metric}",
                    "ticker": stock_record["ticker"], "cik": stock_record.get("cik"),
                    "value": round(value, 8), "unit": unit, "start": dates[0], "end": dates[-1],
                    "inputs": {
                        "prices": stock_record["id"], "benchmark": benchmark_record["id"], "horizon": horizon,
                        "sessions": dates,
                    },
                    "status": "ok",
                    "notes": [
                        f"Regularised logistic direction model on rolling price features; "
                        f"{direction_result.observations} observations.",
                        "No reliable edge." if not direction_result.reliable_edge else
                        "The measured sample has a small positive edge; it is not a buy or sell signal.",
                    ],
                }
                context.remember(record)
                records.append(record)
                summaries[str(horizon)]["records"].append(record["id"])
        else:
            warnings.append(f"{horizon}-session direction unavailable: {direction.reason}")

    if not records:
        return ToolResult(status="unsupported", source="outlook", warnings=warnings)
    overview = {
        "ticker": stock_record["ticker"], "benchmark": "SPY", "start": dates[0], "end": dates[-1],
        "trading_days": len(dates), "horizons": summaries,
        "method": "Empirical 80% forward-return ranges, adaptive conformal calibration, earnings jump adjustment, "
                  "HAR volatility, down-day beta and selloff replay on XNYS sessions.",
    }
    return ToolResult(status="ok", data=overview, ids=[record["id"] for record in records],
                      source=f"{stock_record['source']} outlook", warnings=warnings)


TOOL = Tool(
    "get_outlook",
    "Build host-owned empirical risk forecasts from adjusted stock and SPY prices. Returns citable records for "
    "80% own/relative return ranges, trailing-SPY probability, HAR volatility, down-day beta and selloff context.",
    GetOutlookInput,
    run,
    "outlook",
)
