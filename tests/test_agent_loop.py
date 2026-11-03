import json

import httpx
import openai
from fake_llm import FakeClient, reply, tool_results
from pydantic import BaseModel
from sec_files import make_context

from research_assistant import config
from research_assistant.agents.loop import Finish, run_loop
from research_assistant.agents.trace import Trace
from research_assistant.tools import registry


class Answer(BaseModel):
    cik: str


FINISH = Finish("submit_answer", "Hand in the answer.", Answer)
FIND_APPLE = reply("Looking Apple up first.", [("find_company", {"query": "AAPL"})])


def submit_found_cik(messages):
    return reply(tool_calls=[("submit_answer", {"cik": tool_results(messages)[-1]["data"]["matches"][0]["cik"]})])


def start(tmp_path, client, max_steps=5, **options):
    trace = Trace(tmp_path / "trace.jsonl", "run-1")
    messages = [{"role": "user", "content": "What is Apple's CIK?"}]
    result = run_loop(client, "fake-model", {"store": False}, messages, make_context(tmp_path), FINISH, trace,
                      max_steps=max_steps, **options)
    return result, messages, trace


def events(trace):
    return [json.loads(line) for line in trace.path.read_text(encoding="utf-8").splitlines()]


def test_runs_tools_until_the_finish_tool_and_traces_every_step(tmp_path):
    client = FakeClient(FIND_APPLE, submit_found_cik)
    result, messages, trace = start(tmp_path, client)
    assert result.status == "finished" and result.output.cik == "0000320193" and result.steps == 2
    request = client.requests[0]
    assert {t["function"]["name"] for t in request["tools"]} == set(registry.TOOLS) | {"submit_answer"}
    assert request["store"] is False and not {"max_tokens", "max_completion_tokens", "tool_choice"} & set(request)
    logged = events(trace)
    assert [e["kind"] for e in logged] == ["model_call", "tool_call", "model_call", "finish"]
    assert logged[0]["content"] == "Looking Apple up first." and logged[0]["usage"]["total_tokens"] == 15
    assert logged[1]["name"] == "find_company" and logged[1]["result"]["status"] == "ok"
    assert trace.totals == {"model_calls": 2, "tool_calls": 1, "prompt_tokens": 20, "completion_tokens": 10,
                            "total_tokens": 30, "cached_tokens": None, "cost": None}
    assert messages[-1]["role"] == "tool" and messages[-1]["content"] == "Submitted."


def test_invalid_finish_arguments_go_back_to_the_model(tmp_path):
    def fixed(messages):
        assert "cik: Field required" in messages[-1]["content"]
        return reply(tool_calls=[("submit_answer", {"cik": "320193"})])

    result, _, trace = start(tmp_path, FakeClient(reply(tool_calls=[("submit_answer", {})]), fixed))
    assert result.status == "finished" and result.output.cik == "320193"
    assert [e["valid"] for e in events(trace) if e["kind"] == "finish"] == [False, True]


def test_a_text_only_reply_gets_a_nudge(tmp_path):
    result, messages, trace = start(tmp_path, FakeClient(reply("I think it is 320193."),
                                                         reply(tool_calls=[("submit_answer", {"cik": "320193"})])))
    assert result.status == "finished" and result.steps == 2
    assert messages[2] == {"role": "user", "content": "Call a tool, or call submit_answer to hand in your answer."}
    assert "nudge" in [e["kind"] for e in events(trace)]


def test_a_repeated_call_is_not_run_again(tmp_path, monkeypatch):
    calls = []
    real = registry.call
    monkeypatch.setattr(registry, "call", lambda *a: calls.append(a[0]) or real(*a))
    result, _, trace = start(tmp_path, FakeClient(FIND_APPLE, FIND_APPLE, submit_found_cik))
    assert result.status == "finished" and calls == ["find_company"]
    repeated = [e for e in events(trace) if e["kind"] == "tool_call"][1]
    assert repeated["repeat_of"] == 1 and "same arguments as step 1" in repeated["result"]["warnings"][-1]


def test_a_role_runs_only_its_own_tools(tmp_path, monkeypatch):
    calls = []
    real = registry.call
    monkeypatch.setattr(registry, "call", lambda *a: calls.append(a[0]) or real(*a))

    def refused(messages):
        result = tool_results(messages)[-1]
        assert result["status"] == "invalid" and result["source"] == "agent loop"
        assert "'get_financials' is not one of this role's tools (find_company)" in result["warnings"][0]
        return reply(tool_calls=[("submit_answer", {"cik": "unknown"})])

    client = FakeClient(reply(tool_calls=[("get_financials", {"cik": "320193"})]), refused)
    result, _, trace = start(tmp_path, client, tool_names=["find_company"])
    assert result.status == "finished" and calls == []
    assert {t["function"]["name"] for t in client.requests[0]["tools"]} == {"find_company", "submit_answer"}
    [logged] = [e for e in events(trace) if e["kind"] == "tool_call"]
    assert logged["name"] == "get_financials" and logged["result"]["status"] == "invalid"

    # A role with no registry tools sees only its finish tool.
    client = FakeClient(reply(tool_calls=[("submit_answer", {"cik": "unknown"})]))
    start(tmp_path / "none", client, tool_names=[])
    assert [t["function"]["name"] for t in client.requests[0]["tools"]] == ["submit_answer"]


def test_bad_json_arguments_come_back_invalid(tmp_path):
    def check(messages):
        assert tool_results(messages)[-1]["status"] == "invalid"
        return reply(tool_calls=[("submit_answer", {"cik": "unknown"})])

    result, _, _ = start(tmp_path, FakeClient(reply(tool_calls=[("find_company", "{not json")]), check))
    assert result.status == "finished"


def test_the_step_guard_asks_for_the_best_answer_and_marks_it(tmp_path):
    client = FakeClient(FIND_APPLE, reply(tool_calls=[("find_company", {"query": "MSFT"})]), submit_found_cik)
    result, messages, trace = start(tmp_path, client, max_steps=2)
    assert result.status == "stopped_at_limit" and result.output.cik == "0000789019" and result.steps == 3
    assert client.requests[-1]["tool_choice"] == {"type": "function", "function": {"name": "submit_answer"}}
    assert "step limit (2 model calls) is reached" in client.requests[-1]["messages"][-1]["content"]
    assert "stopped_at_limit" in [e["kind"] for e in events(trace)]


def test_the_step_guard_never_errors_even_when_the_last_call_fails(tmp_path):
    no_answer = start(tmp_path / "a", FakeClient(FIND_APPLE, reply("Sorry, no answer.")), max_steps=1)[0]
    assert no_answer.status == "stopped_at_limit" and no_answer.output is None
    stray = start(tmp_path / "b", FakeClient(FIND_APPLE, reply(tool_calls=[("find_company", {"query": "X"})])),
                  max_steps=1)
    assert stray[0].output is None and stray[1][-1]["content"] == "Not run: the step limit is reached."
    error = openai.APIConnectionError(request=httpx.Request("POST", "https://example.invalid"))
    broken = start(tmp_path / "c", FakeClient(FIND_APPLE, error), max_steps=1)[0]
    assert broken.status == "stopped_at_limit" and broken.output is None and broken.error


def test_a_model_failure_is_a_failed_result_not_an_exception(tmp_path):
    error = openai.APIConnectionError(request=httpx.Request("POST", "https://example.invalid"))
    result, _, trace = start(tmp_path, FakeClient(FIND_APPLE, error))
    assert result.status == "failed" and result.output is None and result.steps == 2
    assert "unavailable" in result.error and "example.invalid" not in result.error
    assert events(trace)[-1]["kind"] == "error"


def test_a_reply_that_is_not_json_is_retried_then_fails_cleanly(tmp_path):
    cut_off = json.JSONDecodeError("Expecting value", "\n" * 12, 12)
    result, _, _ = start(tmp_path, FakeClient(FIND_APPLE, cut_off, submit_found_cik))
    assert result.status == "finished" and result.steps == 2
    result, _, trace = start(tmp_path, FakeClient(*[cut_off] * (config.AGENT_BAD_REPLY_RETRIES + 1)))
    assert result.status == "failed" and events(trace)[-1]["type"] == "BadReply"


def test_the_serving_host_is_traced_so_a_fallback_is_never_silent(tmp_path):
    client = FakeClient(reply(tool_calls=[("find_company", {"query": "AAPL"})], provider="Baidu"),
                        lambda m: reply(tool_calls=[("submit_answer", {"cik": "320193"})], provider="DeepInfra"))
    _, _, trace = start(tmp_path, client)
    assert [e["provider"] for e in events(trace) if e["kind"] == "model_call"] == ["Baidu", "DeepInfra"]
    assert trace.hosts == ["Baidu", "DeepInfra"]


def test_cached_prompt_tokens_are_totalled_per_role_when_the_provider_reports_them(tmp_path):
    trace = Trace(tmp_path / "trace.jsonl", "run-1")
    with trace.acting_as("filings"):
        trace.write("model_call", usage={"prompt_tokens": 100, "prompt_tokens_details": {"cached_tokens": 80}})
        trace.write("model_call", usage={"prompt_tokens": 120, "prompt_tokens_details": {"cached_tokens": 96}})
    with trace.acting_as("market"):
        trace.write("model_call", usage={"prompt_tokens": 50, "prompt_tokens_details": None})
    assert trace.totals["cached_tokens"] == 176 and trace.by_agent["filings"]["cached_tokens"] == 176
    assert trace.by_agent["market"]["cached_tokens"] is None  # not reported, which is not the same as zero


def test_reasoning_details_are_sent_back_but_not_traced(tmp_path):
    details = [{"type": "reasoning.text", "text": "private chain of thought"}]
    client = FakeClient(reply(tool_calls=[("find_company", {"query": "AAPL"})], extra={"reasoning_details": details}),
                        submit_found_cik)
    _, messages, trace = start(tmp_path, client)
    assert messages[1]["reasoning_details"] == details
    assert "private chain of thought" not in trace.path.read_text(encoding="utf-8")


def test_cancelling_stops_before_the_next_model_call_and_skips_the_steps_other_tools(tmp_path):
    context = make_context(tmp_path)

    def cancel_while_asking(messages):  # the user cancels while this model call is out
        context.stop.set()
        return reply(tool_calls=[("find_company", {"query": "AAPL"})])

    trace = Trace(tmp_path / "trace.jsonl", "run-1")
    result = run_loop(FakeClient(cancel_while_asking), "fake-model", {}, [{"role": "user", "content": "?"}], context,
                      FINISH, trace)
    assert result.status == "stopped" and result.output is None and result.steps == 1
    logged = events(trace)
    assert [e["kind"] for e in logged] == ["model_call", "tool_call", "cancelled"]
    assert logged[1]["result"]["warnings"] == ["Not run: the run was cancelled."]
