"""The fixed tool list (REFERENCE §8: no dynamic tools). Agents read `schemas()`; the host runs `call()`."""
from pydantic import ValidationError

from ..data.errors import DataError
from . import (calculate, find_company, get_financials, get_prices, list_filings, read_filing_section, screen,
               verify_against_filing)
from .result import Tool, ToolContext, ToolResult

TOOLS: dict[str, Tool] = {tool.name: tool for tool in (
    find_company.TOOL, get_financials.TOOL, calculate.TOOL, list_filings.TOOL, read_filing_section.TOOL,
    get_prices.TOOL, screen.TOOL, verify_against_filing.TOOL)}


def schemas(names: list[str] | None = None) -> list[dict]:
    return [TOOLS[name].schema() for name in (names or TOOLS)]


def call(name: str, arguments: dict, context: ToolContext) -> ToolResult:
    """Run one tool. Bad arguments and provider failures come back as a status, never an exception."""
    tool = TOOLS.get(name)
    if tool is None:
        return ToolResult(status="invalid", source="registry", warnings=[f"Unknown tool {name!r}. Tools: {', '.join(TOOLS)}."])
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
