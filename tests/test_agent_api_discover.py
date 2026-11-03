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
    assert run["questions"]["terms"] == [LARGE]
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
