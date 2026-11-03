import json

import httpx
import openai
from fake_llm import FakeClient, reply, resubmit, tool_results
from sec_files import make_context

from research_assistant.agents import team
from research_assistant.model_access import ModelSettings

SETTINGS = ModelSettings("openrouter", "OpenRouter", "fake-model", "key", "https://openrouter.ai/api/v1")
ERROR = openai.APIConnectionError(request=httpx.Request("POST", "https://example.invalid"))
QUESTION = "Is Apple profitable, and what events has it reported?"
PLAN = reply("1. find_company AAPL\n2. ask_fundamentals for the margin\n3. ask_filings for 8-K events")
FUNDAMENTALS_TASK = "Apple (AAPL, CIK 0000320193): revenue and operating margin for the latest fiscal year."
FILINGS_TASK = "Apple (AAPL, CIK 0000320193): recent 8-K events."


def calls(*pairs):
    return reply(tool_calls=list(pairs))


def by_source(messages):
    return {result["source"]: result for result in tool_results(messages)}


# The fundamentals analyst: two figures, one calculation, two findings.
def fundamentals_financials(messages):
    return calls(("get_financials", {"cik": "0000320193", "metrics": ["revenue", "operating_income"], "years": 1}))


def latest(messages, metric):
    return by_source(messages)["SEC companyfacts"]["data"]["metrics"][metric]["values"][0]["id"]


def fundamentals_margin(messages):
    inputs = {"numerator": latest(messages, "operating_income"), "denominator": latest(messages, "revenue")}
    return calls(("calculate", {"formula": "ratio", "inputs": inputs}))


def fundamentals_submit(messages):
    margin = by_source(messages)["calculate"]["ids"][0]
    findings = [{"text": "Apple's operating margin was {calc:%s} in the fiscal year ended 2025-09-27." % margin,
                 "kind": "calculation", "materiality": "central"},
                {"text": "Revenue was {fact:%s}." % latest(messages, "revenue"), "kind": "fact"}]
    return calls(("submit_findings", {"findings": findings}))


# The filings analyst: tries a tool that isn't its own, then lists 8-Ks.
def filings_submit(messages):
    filing = tool_results(messages)[-1]["ids"][0]
    return calls(("submit_findings", {"findings": [{"text": "Apple reported a material event on an 8-K.",
                                                    "citations": [filing]}],
                                      "gaps": ["Item 1A was not read."]}))


def coordinator_merge(messages):
    results = by_source(messages)
    margin, revenue = results["fundamentals analyst"]["data"]["findings"]
    [event] = results["filings analyst"]["data"]["findings"]
    draft = {"summary": [{"text": margin["text"], "kind": "calculation", "materiality": "central",
                          "id": margin["claim"]}],
             "key_numbers": [{"text": "Revenue reached {fact:%s} in the fiscal year ended 2025-09-27."
                              % revenue["citations"][0], "kind": "fact", "id": revenue["claim"]}],
             "risks": [{"text": event["text"], "citations": event["citations"], "id": event["claim"]}],
             "bear_case": [{"text": "Material events can change the picture between annual reports.",
                            "citations": [event["claim"]]}],
             "limitations": results["filings analyst"]["data"]["gaps"]}
    return calls(("submit_report", draft))


def run(tmp_path, *script):
    client = FakeClient(*script)
    result = team.run(QUESTION, client, SETTINGS, make_context(tmp_path), trace_dir=tmp_path / "traces")
    events = [json.loads(line) for line in result.trace_path.read_text(encoding="utf-8").splitlines()]
    return result, client, events


def test_the_coordinator_asks_analysts_and_merges_their_findings(tmp_path):
    result, client, events = run(
        tmp_path, PLAN, calls(("find_company", {"query": "AAPL"})),
        calls(("ask_fundamentals", {"task": FUNDAMENTALS_TASK}), ("ask_filings", {"task": FILINGS_TASK})),
        fundamentals_financials, fundamentals_margin, fundamentals_submit,
        calls(("get_financials", {"cik": "320193"})), calls(("list_filings", {"cik": "320193", "forms": ["8-K"]})),
        filings_submit, coordinator_merge, resubmit)
    assert result.status == "finished" and not result.report.flags

    # Each role sees its own tools only, and an analyst starts from the question and its task.
    def tools(n):
        return {t["function"]["name"] for t in client.requests[n]["tools"]}
    assert tools(1) == {"find_company", "calculate", "screen", "ask_fundamentals", "ask_filings", "ask_market",
                        "submit_report"}
    assert tools(3) == {"find_company", "get_financials", "calculate", "verify_against_filing", "submit_findings"}
    assert tools(6) == {"find_company", "read_filing_section", "list_filings", "submit_findings"}
    assert client.requests[3]["messages"][1]["content"] == (f"The user's question: {QUESTION}\n\n"
                                                            f"Your task from the coordinator:\n{FUNDAMENTALS_TASK}")

    # The trace says which role did what; the analysts' work sits inside the coordinator's request.
    assert {e.get("agent") for e in events} == {None, "coordinator", "fundamentals", "filings"}
    asked = [(e["agent"], e["task"]) for e in events if e["kind"] == "analyst_start"]
    assert asked == [("fundamentals", FUNDAMENTALS_TASK), ("filings", FILINGS_TASK)]
    tool_calls = [(e["agent"], e["name"], e["result"]["status"]) for e in events if e["kind"] == "tool_call"]
    assert tool_calls == [("coordinator", "find_company", "ok"), ("fundamentals", "get_financials", "ok"),
                          ("fundamentals", "calculate", "ok"), ("coordinator", "ask_fundamentals", "ok"),
                          ("filings", "get_financials", "invalid"), ("filings", "list_filings", "ok"),
                          ("coordinator", "ask_filings", "ok")]
    end = events[-1]
    assert {agent: totals["model_calls"] for agent, totals in end["by_agent"].items()} == {
        "coordinator": 5, "fundamentals": 3, "filings": 3}
    assert end["totals"]["model_calls"] == 11 and end["totals"]["tool_calls"] == 7

    # Report claims keep the analysts' claim IDs: repeated unchanged stays v1, reworded becomes v2.
    margin_claim = next(e for e in events if e["kind"] == "analyst_end" and e["agent"] == "fundamentals")["claims"]
    summary, numbers = result.report.sections["summary"][0], result.report.sections["key_numbers"][0]
    assert f"{summary.id} v1" == margin_claim["new"][0] and summary.version == 1
    assert numbers.version == 2 and [v["author"] for v in end["claims"][numbers.id]] == ["fundamentals", "coordinator"]
    assert result.report.sections["risks"][0].version == 1 and result.report.limitations == ["Item 1A was not read."]
    # Citing a finding by its claim ID brings the records it cites.
    risk, bear = result.report.sections["risks"][0], result.report.sections["bear_case"][0]
    assert bear.citations == [risk.id, *risk.citations] and bear.status == "cited"
    assert f"`{risk.id}` filings analyst finding (v1): Apple reported a material event on an 8-K. Cites `filing-" \
        in result.markdown

    assert "- Condition: C (analyst team)" in result.markdown and "## Who did what" in result.markdown
    assert (f"- fundamentals analyst (finished, 3 model calls, 2 findings): {FUNDAMENTALS_TASK}" in result.markdown)
    assert "- Apple's operating margin was 32.0% in the fiscal year ended 2025-09-27. [1]" in result.markdown


def test_the_self_review_names_the_citations_a_reused_claim_id_had(tmp_path):
    # Live check 3 Nov 2026: the coordinator kept analysts' claim IDs without their citations.
    def uncited(messages):
        [event] = by_source(messages)["filings analyst"]["data"]["findings"]
        return calls(("submit_report", {"risks": [{"text": "Management reports material events on 8-Ks.",
                                                   "id": event["claim"]}]}))

    def recited(messages):
        request = messages[-1]["content"]
        [event] = by_source(messages)["filings analyst"]["data"]["findings"]
        assert f"risks[0] ({event['claim']}): No citation" in request
        assert f"Its earlier version cited {event['citations'][0]}; the claim ID in `id` doesn't cite them" in request
        return calls(("submit_report", {"risks": [{"text": "Management reports material events on 8-Ks.",
                                                   "id": event["claim"], "citations": event["citations"]}]}))

    result, _, events = run(tmp_path, PLAN, calls(("ask_filings", {"task": FILINGS_TASK})),
                            calls(("list_filings", {"cik": "320193", "forms": ["8-K"]})), filings_submit,
                            uncited, recited)
    assert result.status == "finished" and not result.report.flags
    risk = result.report.sections["risks"][0]
    assert risk.version == 3 and [v["author"] for v in events[-1]["claims"][risk.id]] == ["filings", "coordinator",
                                                                                          "coordinator"]


def test_a_failed_analyst_is_reported_and_a_follow_up_continues_its_conversation(tmp_path):
    def retry(messages):
        market = tool_results(messages)[-1]
        assert market["status"] == "unavailable" and "handed in no findings" in market["warnings"][0]
        return calls(("ask_market", {"task": "Try again: three-year volatility."}))

    def report(messages):
        assert tool_results(messages)[-1]["data"]["gaps"] == ["Prices were not fetched."]
        return calls(("submit_report", {"limitations": ["The market analyst could not fetch prices."]}))

    result, client, events = run(tmp_path, PLAN, calls(("ask_market", {"task": "Apple: three-year volatility."})),
                                 ERROR, retry, calls(("submit_findings", {"gaps": ["Prices were not fetched."]})), report,
                                 resubmit)
    assert result.status == "finished" and "## Summary (abstained)" in result.markdown
    follow_up = client.requests[4]["messages"]  # plan, coordinator, market (fails), coordinator, market again
    assert follow_up[1]["content"].endswith("Your task from the coordinator:\nApple: three-year volatility.")
    assert follow_up[-1] == {"role": "user", "content": "Follow-up from the coordinator:\nTry again: three-year volatility."}
    ends = [(e["status"], e["findings"]) for e in events if e["kind"] == "analyst_end"]
    assert ends == [("failed", 0), ("finished", 0)]
    assert [e["follow_up"] for e in events if e["kind"] == "analyst_start"] == [False, True]
    assert "market and valuation analyst (failed, 1 model calls, 0 findings)" in result.markdown
