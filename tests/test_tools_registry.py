from dataclasses import replace
from datetime import datetime, timezone

import httpx
from sec_files import NoWait, SecFiles, make_context

from research_assistant.data.sec import SecClient
from research_assistant.tools import registry
from research_assistant.tools.result import ToolContext, ToolResult

PHASE_1_TOOLS = {"find_company", "get_financials", "calculate", "list_filings", "read_filing_section", "get_prices",
                 "screen", "verify_against_filing"}
DATA_TOOLS = {"get_macro"}  # REFERENCE §10's November additions


def test_every_tool_has_a_chat_completions_schema():
    schemas = registry.schemas()
    assert {s["function"]["name"] for s in schemas} == PHASE_1_TOOLS | DATA_TOOLS
    for schema in schemas:
        assert schema["type"] == "function" and schema["function"]["description"]
        assert schema["function"]["parameters"]["type"] == "object"


def test_results_have_the_common_shape(tmp_path):
    result = registry.call("find_company", {"query": "AAPL"}, make_context(tmp_path))
    assert isinstance(result, ToolResult)
    assert set(result.model_dump()) == {"status", "data", "ids", "source", "warnings"}


def test_unknown_tool_and_bad_arguments_are_invalid_not_raised(tmp_path):
    context = make_context(tmp_path)
    assert registry.call("buy_stock", {}, context).status == "invalid"
    bad = registry.call("get_financials", {"cik": "AAPL", "years": 0}, context)
    assert bad.status == "invalid" and any(w.startswith("cik:") for w in bad.warnings) and any(w.startswith("years:") for w in bad.warnings)


def test_an_unexpected_tool_bug_is_a_status_not_an_exception(tmp_path, monkeypatch):
    def broken(args, context):
        raise ArithmeticError("boom")
    monkeypatch.setitem(registry.TOOLS, "find_company", replace(registry.TOOLS["find_company"], run=broken))
    result = registry.call("find_company", {"query": "AAPL"}, make_context(tmp_path))
    assert result.status == "unavailable" and "find_company failed unexpectedly (ArithmeticError: boom)" in result.warnings[0]


def test_provider_failures_become_statuses(tmp_path):
    missing = registry.call("get_financials", {"cik": "1234"}, make_context(tmp_path))
    assert missing.status == "not_found" and missing.source == "SEC companyfacts"
    offline = SecClient("", tmp_path / "empty", transport=httpx.MockTransport(SecFiles()), limiter=NoWait())
    context = ToolContext(cutoff=datetime(2026, 11, 1, tzinfo=timezone.utc), sec=offline, cache_dir=tmp_path)
    unconfigured = registry.call("list_filings", {"cik": "320193"}, context)
    assert unconfigured.status == "unavailable" and "SEC_USER_AGENT" in unconfigured.warnings[0]
