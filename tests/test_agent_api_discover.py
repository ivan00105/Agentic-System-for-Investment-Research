import json

from fake_llm import FakeClient, reply
from test_agent_api import start, wait

LARGE = {"term": "large", "definition": "revenue of at least $10 billion", "question": "What revenue counts as large?"}
SPEC = reply(tool_calls=[("submit_screen_spec", {"rank_by": "operating_margin", "terms": [LARGE]})])


def waiting(web, run_id) -> dict:
    for _ in range(500):
        run = web.get(f"/api/agent-runs/{run_id}").json()
        if run["status"] == "waiting":
            return run
        assert run["status"] == "running", run
    raise AssertionError("The run never asked its questions")


def test_discover_waits_for_the_users_answers_with_the_draft_spec_in_view(web):
    web.model = FakeClient(SPEC, reply(tool_calls=[("submit_screen_spec", {
        "rank_by": "operating_margin", "terms": [{**LARGE, "definition": "revenue of at least $100 billion"}]})]))
    run_id = start(web, "Find large companies.", discover={"tickers": ["aapl", "MSFT"]})
    run = waiting(web, run_id)
    assert run["questions"]["terms"] == [{**LARGE, "options": []}]
    assert run["questions"]["shown"][0].startswith("Universe: your list, 2 companies")
    assert any("proposed: waiting for the user's answer" in line for line in run["questions"]["shown"])
    assert web.get("/api/agent-runs").json()["items"][0]["status"] == "waiting"

    answered = web.post(f"/api/agent-runs/{run_id}/answers", json={"answers": {"large": "revenue over $100 billion"}})
    assert answered.status_code == 200 and answered.json()["status"] == "running"
    run = wait(web, run_id)
    assert run["condition"] == "Discover (B (single agent))" and run["questions"] is None
    events = [json.loads(line) for line in (web.traces / f"{run_id}.jsonl").read_text(encoding="utf-8").splitlines()]
    [clarify] = [e for e in events if e["kind"] == "clarify"]
    assert clarify["answer"] == "revenue over $100 billion"
    [spec] = [e for e in events if e["kind"] == "screen_spec"]
    assert spec["terms"] == {"large": "user"}
    assert web.post(f"/api/agent-runs/{run_id}/answers", json={"answers": {}}).status_code == 409


def test_cancelling_a_waiting_discover_stops_it_before_the_screen(web):
    web.model = FakeClient(SPEC)
    run_id = start(web, "Find large companies.", discover={"name": "sp500_tech"})
    waiting(web, run_id)
    assert web.post(f"/api/agent-runs/{run_id}/cancel", json={}).json()["status"] == "stopping"
    run = wait(web, run_id)
    assert run["status"] == "stopped"
    report = web.get(f"/api/agent-runs/{run_id}/report").json()
    assert report["error"] is None and report["discover"]["counts"] == {} and report["discover"]["candidates"] == []
    assert "assumed: not confirmed by the user" in report["markdown"]


def test_discover_refuses_a_cutoff_and_unknown_tickers_before_starting(web):
    refused = web.post("/api/agent-runs", json={"question": "Find.", "cutoff": "2025-01-01",
                                                "discover": {"name": "sp500_tech"}})
    assert refused.status_code == 422 and "current data only" in refused.json()["error"]["message"]
    unknown = web.post("/api/agent-runs", json={"question": "Find.", "discover": {"tickers": ["AAPL", "NOPE1"]}})
    assert unknown.status_code == 422 and unknown.json()["error"]["message"].endswith("NOPE1.")
    assert web.post("/api/agent-runs", json={"question": "Find.", "discover": {}}).status_code == 422
    assert web.get("/api/agent-runs").json() == {"items": []}


def test_a_question_can_research_as_of_a_past_day(web, monkeypatch):
    from research_assistant import cli
    seen = []

    def single(question, client, settings, context, trace):
        seen.append(context.cutoff.isoformat())
        trace.write("run_start", question=question, condition="B (single agent)")
        trace.write("run_end", status="finished")

    monkeypatch.setitem(cli.CONDITIONS, "B", single)
    wait(web, start(web, condition="B", cutoff="2025-06-30"))
    assert seen == ["2025-06-30T23:59:59.999999+00:00"]


def test_an_edit_sent_with_the_answers_is_used_even_without_the_review_option(web):
    web.model = FakeClient(SPEC)
    run_id = start(web, "Find large companies.", discover={"tickers": ["AAPL"]})
    waiting(web, run_id)
    edited = {"rank_by": "revenue", "top_k": 2, "terms": [LARGE]}
    assert web.post(f"/api/agent-runs/{run_id}/answers", json={"answers": {}, "spec": edited}).status_code == 200
    wait(web, run_id)
    events = [json.loads(line) for line in (web.traces / f"{run_id}.jsonl").read_text(encoding="utf-8").splitlines()]
    [spec] = [e for e in events if e["kind"] == "screen_spec"]
    assert (spec["top_k"], spec["spec"]["rank_by"], spec["terms"]) == (2, "revenue", {"large": "accepted"})


def test_without_the_review_option_a_spec_with_no_vague_terms_runs_at_once(web):
    web.model = FakeClient(reply(tool_calls=[("submit_screen_spec", {"rank_by": "revenue", "top_k": 1,
                                                                     "filters": [{"metric": "revenue", "op": ">", "value": 1e15}]})]))
    run = wait(web, start(web, "Find companies.", discover={"tickers": ["AAPL"]}))
    assert run["status"] == "finished" and not any(line["kind"] == "questions" for line in run["progress"])


def test_a_professional_run_waits_to_review_the_spec_and_takes_an_edit(web):
    web.model = FakeClient(reply(tool_calls=[("submit_screen_spec", {"rank_by": "operating_margin"})]))
    run_id = start(web, "Find companies.", discover={"tickers": ["AAPL"]}, edit_spec=True, model="other/model")
    run = waiting(web, run_id)
    assert run["questions"]["terms"] == [] and run["questions"]["spec"]["rank_by"] == "operating_margin"
    bad = web.post(f"/api/agent-runs/{run_id}/answers", json={"answers": {}, "spec": {"rank_by": "pe"}})
    assert bad.status_code == 422 and "rank_by" in bad.json()["error"]["message"]
    edited = {"rank_by": "revenue", "filters": [{"metric": "revenue", "op": ">", "value": 1e15}]}
    assert web.post(f"/api/agent-runs/{run_id}/answers", json={"answers": {}, "spec": edited}).status_code == 200
    wait(web, run_id)
    events = [json.loads(line) for line in (web.traces / f"{run_id}.jsonl").read_text(encoding="utf-8").splitlines()]
    assert events[0]["model"] == "other/model" and web.model.requests[0]["model"] == "other/model"
    [spec] = [e for e in events if e["kind"] == "screen_spec"]
    assert spec["spec"]["rank_by"] == "revenue" and spec["spec"]["filters"][0]["value"] == 1e15


def test_the_screener_reads_the_preferences_note(web):
    web.model = FakeClient(SPEC)
    run_id = start(web, "Find companies.", discover={"tickers": ["AAPL"]}, preferences="Comfort with price swings: low.")
    run = waiting(web, run_id)
    assert run["question"] == "Find companies." and run["preferences"] == "Comfort with price swings: low."
    assert web.model.requests[0]["messages"][1]["content"].endswith(
        "<preferences>\nComfort with price swings: low.\n</preferences>")
    assert "time horizon" in web.model.requests[0]["messages"][0]["content"]  # the screener's prompt says how
    web.post(f"/api/agent-runs/{run_id}/cancel", json={})
    wait(web, run_id)


def test_the_page_gets_each_terms_options_and_a_picked_one_sets_the_term(web):
    options = [{"definition": "revenue of at least $10 billion", "recommended": True},
               {"definition": "revenue of at least $50 billion"}]
    web.model = FakeClient(reply(tool_calls=[("submit_screen_spec", {
        "rank_by": "operating_margin", "terms": [{**LARGE, "options": options}]})]), reply(tool_calls=[(
            "submit_screen_spec", {"rank_by": "operating_margin", "terms": [
                {**LARGE, "definition": "revenue of at least $50 billion", "options": options}]})]))
    run_id = start(web, "Find large companies.", discover={"tickers": ["AAPL"]})
    run = waiting(web, run_id)
    assert run["questions"]["terms"][0]["options"] == [options[0], {**options[1], "recommended": False}]
    web.post(f"/api/agent-runs/{run_id}/answers", json={"answers": {"large": "revenue of at least $50 billion"}})
    wait(web, run_id)
    assert "- large: revenue of at least $50 billion" in web.model.requests[1]["messages"][-1]["content"]
    events = [json.loads(line) for line in (web.traces / f"{run_id}.jsonl").read_text(encoding="utf-8").splitlines()]
    assert next(e for e in events if e["kind"] == "screen_spec")["terms"] == {"large": "user"}


def test_a_find_over_every_sec_filer_tells_the_screener_the_size_not_the_names(web):
    web.model = FakeClient(SPEC)
    run_id = start(web, "Find large companies.", discover={"name": "sec_all"})
    run = waiting(web, run_id)
    assert run["questions"]["shown"][0].startswith("Universe: Every SEC filer with a ticker")
    prompt = web.model.requests[0]["messages"][0]["content"]
    assert "aren't listed here" in prompt and "- AAPL:" not in prompt
    web.post(f"/api/agent-runs/{run_id}/cancel", json={})
    wait(web, run_id)
