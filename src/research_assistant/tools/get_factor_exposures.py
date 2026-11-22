"""Host-owned factor exposure regression on Ken French factors and adjusted prices."""
from datetime import date, timedelta

from pydantic import BaseModel, Field

from .. import config
from ..data import factors, prices as price_data
from ..finance import quant
from .get_prices import GetPricesInput, run as get_prices
from .result import Tool, ToolContext, ToolResult, make_id


class GetFactorExposuresInput(BaseModel):
    ticker: str = Field(min_length=1, max_length=12)
    start: date | None = Field(None)
    end: date | None = Field(None)


def _factor_date(day: str) -> str:
    if len(day) == 8 and day.isdigit():
        return f"{day[:4]}-{day[4:6]}-{day[6:]}"
    return day


def _plain_words(betas: dict[str, float]) -> str:
    size = "small" if betas.get("SMB", 0) > 0.2 else "large" if betas.get("SMB", 0) < -0.2 else "size-neutral"
    style = "value" if betas.get("HML", 0) > 0.2 else "growth" if betas.get("HML", 0) < -0.2 else "style-neutral"
    quality = "profitable" if betas.get("RMW", 0) > 0.2 else "quality-neutral"
    investment = "conservative" if betas.get("CMA", 0) > 0.2 else "investment-neutral"
    return f"Moves like a {size}, {quality}, {investment} {style} stock."


def run(args: GetFactorExposuresInput, context: ToolContext) -> ToolResult:
    end = args.end or price_data.last_known_day(context.cutoff)
    start = args.start or end - timedelta(days=config.PRICE_DEFAULT_LOOKBACK_DAYS)
    price_result = get_prices(GetPricesInput(ticker=args.ticker, start=start, end=end), context)
    if price_result.status != "ok":
        return ToolResult(status=price_result.status, source="factors", warnings=price_result.warnings)
    series = context.records[price_result.ids[0]]
    try:
        five = factors.five_factors(context.cache("factor_cache"))
        mom = factors.momentum(context.cache("factor_cache"))
    except Exception as exc:
        return ToolResult(status="unavailable", source="Ken French",
                          warnings=[f"Factor data is unavailable: {type(exc).__name__}: {exc}."])

    rows = sorted({row["date"]: row["adj_close"] for row in series["rows"]}.items())
    stock_excess, aligned_factors = [], {"MKT-RF": [], "SMB": [], "HML": [], "RMW": [], "CMA": [], "Mom": []}
    for (_, previous), (day, close) in zip(rows, rows[1:], strict=False):
        key = day.replace("-", "")
        factor = five.get(key)
        if factor is None:
            continue
        momentum = mom.get(key)
        if momentum is None:
            continue
        stock_return = close / previous - 1
        rf = factor["RF"]
        stock_excess.append(stock_return - rf)
        for name in ("MKT-RF", "SMB", "HML", "RMW", "CMA"):
            aligned_factors[name].append(factor[name])
        aligned_factors["Mom"].append(momentum)
    outcome = quant.factor_exposure(stock_excess, aligned_factors,
                                    ("MKT-RF", "SMB", "HML", "RMW", "CMA", "Mom"))
    if outcome.value is None:
        return ToolResult(status="unsupported", source="Ken French",
                          warnings=[outcome.reason or "Factor exposures are unavailable."])
    result = outcome.value
    result = quant.FactorExposure(series["ticker"], result.observations, result.intercept,
                                  result.betas, result.r_squared, result.out_of_sample_r_squared)
    record = {
        "id": make_id("factor", series["id"], len(result.betas), result.observations,
                      *[round(result.betas[name], 8) for name in sorted(result.betas)]),
        "kind": "calc", "formula": "factor_exposures", "ticker": series["ticker"],
        "cik": series.get("cik"), "value": result.r_squared, "unit": "ratio",
        "start": rows[0][0] if rows else start.isoformat(), "end": rows[-1][0] if rows else end.isoformat(),
        "inputs": {"prices": series["id"], "provider": "Ken French"},
        "status": "ok",
        "betas": result.betas, "intercept": result.intercept, "observations": result.observations,
        "out_of_sample_r_squared": result.out_of_sample_r_squared,
        "plain_words": _plain_words(result.betas),
        "notes": ["Daily factor regressions describe past exposures, not future returns.",
                  "Factor history is survivorship-free CRSP data, but the stock price window may be shorter."],
    }
    context.remember(record)
    return ToolResult(status="ok", data={**record, "id": record["id"]}, ids=[record["id"]],
                      source="Ken French + adjusted prices",
                      warnings=["Factor betas are a description, not a trading signal."])


TOOL = Tool("get_factor_exposures",
            "Estimate market, size, value, profitability, investment and momentum factor betas for a ticker.",
            GetFactorExposuresInput, run, "factors")
