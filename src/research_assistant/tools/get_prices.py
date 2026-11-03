"""get_prices: a daily price series as of the cutoff, stored whole under one ID for calculate."""
import json
from datetime import date, timedelta

from pydantic import BaseModel, Field

from .. import config
from ..data import companies, prices
from ..data.errors import DataError
from .result import Tool, ToolContext, ToolResult, make_id


class GetPricesInput(BaseModel):
    ticker: str = Field(min_length=1, max_length=12, description="Ticker, e.g. AAPL, BRK.B or SPY (for beta).")
    start: date | None = Field(None, description=f"First day; default {config.PRICE_DEFAULT_LOOKBACK_DAYS} days before the end.")
    end: date | None = Field(None, description="Last day; default and maximum: the research cutoff.")


def run(args: GetPricesInput, context: ToolContext) -> ToolResult:
    last_day = prices.last_known_day(context.cutoff)
    warnings = []
    end = args.end or last_day
    if end > last_day:
        warnings.append(f"End date moved from {end} to {last_day}: later closes were not public at the cutoff.")
        end = last_day
    start = args.start or end - timedelta(days=config.PRICE_DEFAULT_LOOKBACK_DAYS)
    if start > end:
        return ToolResult(status="invalid", source="prices", warnings=[f"Start {start} is after end {end}."])
    rows, source, notes = prices.fetch(args.ticker, start, end, context.cache("price_cache"), context.price_providers)
    rows = [r for r in rows if start.isoformat() <= r["date"] <= end.isoformat()]
    if not rows:
        return ToolResult(status="not_found", source=source, warnings=notes + [f"No trading days between {start} and {end}."])
    preferred = (context.price_providers or prices.provider_order())[:1]
    label = source if [source] == preferred else f"{source} (fallback)"
    ticker = prices.normalize_ticker(args.ticker)
    # Which company this is, so calculate never mixes one company's price with another's share count.
    # ETFs such as SPY are not SEC operating companies and stay None.
    try:
        cik = next((c.cik for c in companies.listed_companies(context.sec).values() if ticker in c.tickers), None)
    except DataError as exc:
        cik = None
        warnings.append(f"Could not look up which company {ticker} is ({exc}); calculate can't check it.")
    # The ID covers the rows themselves: fetched again, Yahoo's adjusted closes can differ by float noise, and a new
    # ID keeps the rows an earlier calculation used frozen beside the new ones (evidence.py rechecks from them).
    record = {"id": make_id("prices", source, ticker, json.dumps(rows, sort_keys=True)), "kind": "prices",
              "ticker": ticker, "cik": cik, "source": source, "start": rows[0]["date"], "end": rows[-1]["date"], "rows": rows}
    context.remember(record)
    last = rows[-1]
    splits = [{"date": r["date"], "ratio": r["split"]} for r in rows if r.get("split") not in (None, 0, 1)]
    data = {"id": record["id"], "ticker": ticker, "cik": cik, "source": source, "start": record["start"], "end": record["end"],
            "trading_days": len(rows), "last": {"date": last["date"], "close": last["close"], "adj_close": last["adj_close"]},
            "first": {"date": rows[0]["date"], "close": rows[0]["close"], "adj_close": rows[0]["adj_close"]},
            "splits": splits, "dividends": sum(1 for r in rows if r.get("dividend")),
            "rows_stored": f"All {len(rows)} daily rows are stored under {record['id']}; pass that ID to calculate."}
    if source == "yfinance":
        warnings.append("Yahoo's close is split-adjusted; the as-traded close was rebuilt from its split history.")
    return ToolResult(status="ok", data=data, ids=[record["id"]], source=label, warnings=notes + warnings)


TOOL = Tool("get_prices", "Daily prices for a ticker up to the research cutoff (as-traded close and dividend-adjusted "
            "close). Returns a series ID for calculate (market_cap, total_return, volatility, max_drawdown, beta).",
            GetPricesInput, run, "prices")
