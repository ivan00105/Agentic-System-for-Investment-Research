import json
import re

import httpx
import openai
from fake_llm import FakeClient, reply, tool_results
from sec_files import make_context

from research_assistant.agents import single_agent
from research_assistant.model_access import ModelSettings

SETTINGS = ModelSettings("openrouter", "OpenRouter", "fake-model", "key", "https://openrouter.ai/api/v1")
PLAN = reply("1. find_company AAPL\n2. get_financials revenue and operating income\n3. calculate the margin",
             provider="Baidu")
ERROR = openai.APIConnectionError(request=httpx.Request("POST", "https://example.invalid"))


def find_apple(messages):
    return reply(tool_calls=[("find_company", {"query": "AAPL"})])


def get_financials(messages):
    cik = tool_results(messages)[-1]["data"]["matches"][0]["cik"]
    return reply(tool_calls=[("get_financials", {"cik": cik, "metrics": ["revenue", "operating_income"], "years": 1})])


def latest(messages, metric):
    financials = next(r for r in reversed(tool_results(messages)) if r["source"] == "SEC companyfacts")
    return financials["data"]["metrics"][metric]["values"][0]["id"]


def calculate_margin(messages):
    inputs = {"numerator": latest(messages, "operating_income"), "denominator": latest(messages, "revenue")}
    return reply(tool_calls=[("calculate", {"formula": "ratio", "inputs": inputs})])


def submit(stray: bool, bull_id: str | None = None):
    def step(messages):
        margin = next(r for r in reversed(tool_results(messages)) if r["source"] == "calculate")["ids"][0]
        revenue = latest(messages, "revenue")
        upside = "Margins above 30% leave room." if stray else "The margin leaves room for investment."
        draft = {"summary": [{"text": "Apple's operating margin was {calc:%s} in the fiscal year ended 2025-09-27."
                              % margin, "kind": "calculation"}],
                 "key_numbers": [{"text": "Revenue was {fact:%s}." % revenue, "kind": "fact"}],
                 "bull_case": [{"text": upside, "citations": [margin], "kind": "interpretation", "id": bull_id}],
                 "limitations": ["No statistical outlook model is available yet."]}
        return reply(tool_calls=[("submit_report", draft)])
    return step


def run(tmp_path, *script, **options):
    client = FakeClient(*script)
    result = single_agent.run("Is Apple profitable?", client, SETTINGS, make_context(tmp_path),
                              trace_dir=tmp_path / "traces", **options)
    events = [json.loads(line) for line in result.trace_path.read_text(encoding="utf-8").splitlines()]
    return result, client, events


def test_plan_loop_check_and_one_self_review_give_a_cited_report(tmp_path):
    def fix(messages):
        flagged = re.search(r"bull_case\[0\] \((claim-\w+)\): '30%' is typed", messages[-1]["content"])
        return submit(stray=False, bull_id=flagged[1])(messages)

    result, client, events = run(tmp_path, PLAN, find_apple, get_financials, calculate_margin, submit(stray=True), fix)
    assert result.status == "finished" and result.error is None and not result.report.flags
    # The fixed claim is version 2 of the same claim; the untouched summary stays version 1.
    first_bull = events[[e["kind"] for e in events].index("check")]["claims"]["new"][2]
    bull, summary = result.report.sections["bull_case"][0], result.report.sections["summary"][0]
    assert first_bull == f"{bull.id} v1" and bull.version == 2 and summary.version == 1
    assert events[-1]["claims"][bull.id][0]["text"] == "Margins above 30% leave room."
    assert [e["claims"]["revised"] for e in events if e["kind"] == "check"] == [[], [f"{bull.id} v2"]]
    assert result.plan.startswith("1. find_company") and "- Model: fake-model (served by Baidu)" in result.markdown
    assert "- Apple's operating margin was 32.0% in the fiscal year ended 2025-09-27. [1]" in result.markdown
    assert "- Revenue was $416.2 billion. [2]" in result.markdown
    assert "## Bull case (cited)" in result.markdown and "## Bear case (abstained)" in result.markdown
    assert "1. `calc-" in result.markdown and "2. `fact-" in result.markdown
    # Plan call has no tools; every request uses the model settings and no output-token cap.
    assert "tools" not in client.requests[0] and client.requests[1]["tools"]
    for request in client.requests:
        assert request["model"] == "fake-model" and request["store"] is False
        assert request["extra_body"]["provider"] == {"require_parameters": True, "allow_fallbacks": True}
        assert not {"max_tokens", "max_completion_tokens"} & set(request)
    assert "2026-11-01" in client.requests[1]["messages"][0]["content"]
    assert "Your plan:\n1. find_company AAPL" in client.requests[1]["messages"][1]["content"]
    kinds = [e["kind"] for e in events]
    assert kinds[:2] == ["run_start", "plan"] and kinds[-1] == "run_end"
    assert kinds.count("check") == 2 and kinds.count("self_review") == 1
    assert events[-1]["totals"]["model_calls"] == 6 and events[-1]["totals"]["tool_calls"] == 3
    assert result.totals == events[-1]["totals"] and events[-1]["markdown"] == result.markdown


def test_a_clean_draft_skips_the_self_review(tmp_path):
    result, client, events = run(tmp_path, PLAN, find_apple, get_financials, calculate_margin, submit(stray=False))
    assert result.status == "finished" and len(client.requests) == 5
    assert "self_review" not in [e["kind"] for e in events]


def test_a_failed_self_review_keeps_the_first_draft_with_its_flags(tmp_path):
    result, _, _ = run(tmp_path, PLAN, find_apple, get_financials, calculate_margin, submit(stray=True), ERROR)
    assert result.status == "finished" and [f.where for f in result.report.flags] == ["bull_case[0]"]
    assert "Margins above 30% leave room. [1] (qualified: see checker flags)" in result.markdown
    assert "The self-review pass ended without a new report" in result.markdown


def test_the_step_guard_gives_a_partial_report_marked_stopped_at_limit(tmp_path):
    result, _, events = run(tmp_path, PLAN, find_apple, get_financials, reply("I need more steps."), max_steps=2)
    assert result.status == "stopped_at_limit" and result.report.flags == []
    assert "stopped at limit" in result.markdown and "## Summary (abstained)" in result.markdown
    assert "The model did not hand in a report (stopped_at_limit)" in result.markdown
    assert "`company-0000320193` Apple Inc." in result.markdown and "`fact-" in result.markdown
    assert events[-1]["status"] == "stopped_at_limit"


def test_a_model_failure_in_the_plan_is_a_failed_run_not_an_exception(tmp_path):
    result, _, events = run(tmp_path, ERROR)
    assert result.status == "failed" and "unavailable" in result.error
    assert "- Run status: failed" in result.markdown and "- Error: " in result.markdown
    assert [e["kind"] for e in events] == ["run_start", "error", "run_end"]
