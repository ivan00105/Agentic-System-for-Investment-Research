import json
import re

import httpx
import openai
from fake_llm import FakeClient, reply, resubmit, tool_results
from sec_files import make_context

from research_assistant.agents import single_agent
from research_assistant.agents.objections import ISSUES
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


def test_a_clean_draft_still_gets_one_self_review_for_the_critics_issue_types(tmp_path):
    # REFERENCE §7: B's self-review looks for the same issue types as D's critic, not only checker flags.
    result, client, events = run(tmp_path, PLAN, find_apple, get_financials, calculate_margin, submit(stray=False),
                                 resubmit)
    assert result.status == "finished" and len(client.requests) == 6 and not result.report.flags
    request = client.requests[5]["messages"][-1]["content"]
    assert request.startswith("Review your report before it is final.") and "checker also found" not in request
    assert all(f"- `{issue}`: " in request for issue in ISSUES)
    summary = result.report.sections["summary"][0]
    assert (f"- {summary.id} v1 [summary[0], calculation, supporting]: Apple's operating margin was 32.0% in the "
            "fiscal year ended 2025-09-27.") in request
    assert "revenue = $416.2 billion, 2024-09-29 to 2025-09-27" in request  # the fact behind the margin calc
    assert [e["kind"] for e in events].count("self_review") == 1
    assert [e["claims"]["unchanged"] for e in events if e["kind"] == "check"][1] == [
        c.id for key in ("summary", "key_numbers", "bull_case") for c in result.report.sections[key]]
    assert all(len(versions) == 1 for versions in events[-1]["claims"].values())


def test_a_second_pass_runs_only_while_the_checker_still_flags(tmp_path):
    result, client, events = run(tmp_path, PLAN, find_apple, get_financials, calculate_margin, submit(stray=False),
                                 resubmit, self_review_passes=2)
    assert len(client.requests) == 6 and [e["kind"] for e in events].count("self_review") == 1


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


def cancelled_run(tmp_path, cancel_on, *script):
    """A run whose user cancels while the model call `cancel_on` is out."""
    context = make_context(tmp_path)

    def cancel(messages):
        context.stop.set()
        return cancel_on(messages)

    result = single_agent.run("Is Apple profitable?", FakeClient(*script, cancel), SETTINGS, context,
                              trace_dir=tmp_path / "traces")
    return result, [json.loads(line) for line in result.trace_path.read_text(encoding="utf-8").splitlines()]


def test_cancelling_gives_a_partial_report_marked_stopped_not_an_error(tmp_path):
    result, events = cancelled_run(tmp_path, get_financials, PLAN, find_apple)
    assert result.status == "stopped" and result.error is None
    assert "- Run status: stopped: the run was cancelled" in result.markdown
    assert "## Summary (abstained)" in result.markdown and "`company-0000320193` Apple Inc." in result.markdown
    assert [e["kind"] for e in events][-3:] == ["tool_call", "cancelled", "run_end"]
    assert events[-1]["status"] == "stopped"


def test_cancelling_during_the_self_review_keeps_the_draft(tmp_path):
    result, events = cancelled_run(tmp_path, submit(stray=False), PLAN, find_apple, get_financials, calculate_margin)
    assert result.status == "stopped" and "## Summary (cited)" in result.markdown
    assert "The self-review pass ended without a new report (stopped)" in result.markdown
    assert events[-1]["status"] == "stopped"


def test_a_run_cancelled_before_it_plans_makes_no_model_call(tmp_path):
    # Codex review: a cancel that came before the plan request still sent it.
    context, client = make_context(tmp_path), FakeClient(PLAN)
    context.stop.set()
    result = single_agent.run("Is Apple profitable?", client, SETTINGS, context, trace_dir=tmp_path / "traces")
    assert result.status == "stopped" and result.error is None and client.requests == []
    events = [json.loads(line) for line in result.trace_path.read_text(encoding="utf-8").splitlines()]
    assert [e["kind"] for e in events] == ["run_start", "run_end"] and events[-1]["status"] == "stopped"
