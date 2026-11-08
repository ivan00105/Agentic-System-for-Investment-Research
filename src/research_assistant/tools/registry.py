"""The fixed tool list (REFERENCE §8: no dynamic tools). Agents read `schemas()`; the host runs `call()`."""
from pydantic import ValidationError

from ..data.errors import DataError
from . import (calculate, find_company, get_financials, get_insider_trades, get_macro, get_peers, get_prices,
               list_filings, read_filing_section, screen, verify_against_filing)
from .result import Tool, ToolContext, ToolResult

TOOLS: dict[str, Tool] = {tool.name: tool for tool in (
    find_company.TOOL, get_financials.TOOL, calculate.TOOL, list_filings.TOOL, read_filing_section.TOOL,
    get_prices.TOOL, screen.TOOL, verify_against_filing.TOOL, get_macro.TOOL, get_insider_trades.TOOL,
    get_peers.TOOL)}


def schemas(names: list[str] | None = None) -> list[dict]:
    """None means every tool; an empty list means none (a role without registry tools)."""
    return [TOOLS[name].schema() for name in (TOOLS if names is None else names)]


def call(name: str, arguments: dict, context: ToolContext, tools: dict[str, Tool] | None = None) -> ToolResult:
    """Run one tool from `tools` (default: the registry; agents add their own, e.g. an analyst to ask).
    Bad arguments and provider failures come back as a status, never an exception."""
    tools = TOOLS if tools is None else tools
    tool = tools.get(name)
    if tool is None:
        return ToolResult(status="invalid", source="registry", warnings=[f"Unknown tool {name!r}. Tools: {', '.join(tools)}."])
    try:
        arguments = tool.input_model.model_validate(arguments)
    except ValidationError as exc:
        problems = [f"{'.'.join(str(part) for part in error['loc']) or 'arguments'}: {error['msg']}" for error in exc.errors()]
        return ToolResult(status="invalid", source=tool.source, warnings=problems)
    try:
        return tool.run(arguments, context)
    except DataError as exc:
        return ToolResult(status="not_found" if exc.code == "not_found" else "unavailable", source=tool.source,
                          warnings=[str(exc)])
    except Exception as exc:  # a bug in one tool must not end the agent's run; the agent sees it and moves on
        return ToolResult(status="unavailable", source=tool.source, warnings=[
            f"{name} failed unexpectedly ({type(exc).__name__}: {exc}). This is a tool bug; don't retry the same call."])
