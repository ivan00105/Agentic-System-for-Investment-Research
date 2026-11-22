"""Long-run summaries of Ken French's published factor strategies."""
from pydantic import BaseModel

from .. import config
from ..data import factors
from ..finance import quant
from .result import Tool, ToolContext, ToolResult, make_id


class GetStrategyLabInput(BaseModel):
    pass


def run(_args: GetStrategyLabInput, context: ToolContext) -> ToolResult:
    try:
        five = factors.five_factors(context.cache("factor_cache"))
        mom = factors.momentum(context.cache("factor_cache"))
    except Exception as exc:
        return ToolResult(status="unavailable", source="Ken French",
                          warnings=[f"Strategy lab data is unavailable: {type(exc).__name__}: {exc}."])

    items = [
        ("value", "HML", five),
        ("size", "SMB", five),
        ("profitability", "RMW", five),
        ("investment", "CMA", five),
    ]
    strategies = []
    warnings = ["No rules were searched or fitted; these are published factor premia."]
    for name, factor_name, source in items:
        points = [(f"{day[:4]}-{day[4:6]}-{day[6:]}", value[factor_name]) for day, value in sorted(source.items())]
        outcome = quant.strategy_stats(name, [day for day, _ in points], [value for _, value in points],
                                       config.TRADING_DAYS_PER_YEAR)
        if outcome.value is None:
            continue
        strategies.append(outcome.value)
    momentum_points = [(f"{day[:4]}-{day[4:6]}-{day[6:]}", value) for day, value in sorted(mom.items())]
    outcome = quant.strategy_stats("momentum", [day for day, _ in momentum_points],
                                   [value for _, value in momentum_points], config.TRADING_DAYS_PER_YEAR)
    if outcome.value is not None:
        strategies.append(outcome.value)
    if not strategies:
        return ToolResult(status="unsupported", source="Ken French",
                          warnings=["Ken French data contained no usable daily strategy rows."])

    records = []
    five_days = [f"{day[:4]}-{day[4:6]}-{day[6:]}" for day in five]
    start = min(five_days) if five_days else None
    end = max(five_days) if five_days else None
    for strategy in strategies:
        record = {
            "id": make_id("strategy", strategy.name, strategy.observations, round(strategy.annualized_return, 8)),
            "kind": "calc", "formula": "strategy_lab", "ticker": None,
            "value": strategy.annualized_return, "unit": "ratio",
            "start": start,
            "end": end,
            "inputs": {"provider": "Ken French"},
            "status": "ok", "observations": strategy.observations,
            "annualized_return": strategy.annualized_return,
            "worst_drawdown": strategy.worst_drawdown,
            "losing_years": strategy.losing_years,
            "name": strategy.name,
        }
        context.remember(record)
        records.append(record)
    warnings.append("Low-volatility sorted portfolios are unavailable here; only the Ken French published factors "
                    "that are downloadable through this provider are shown.")
    data = {"strategies": [record for record in records], "publication_decay": "Not estimated; post-publication "
            "decay requires a separate dated replication and is intentionally not inferred here."}
    return ToolResult(status="ok", data=data, ids=[record["id"] for record in records],
                      source="Ken French", warnings=warnings)


TOOL = Tool("get_strategy_lab",
            "Summarize published Ken French value, size, profitability, investment and momentum factor strategies.",
            GetStrategyLabInput, run, "factors")
