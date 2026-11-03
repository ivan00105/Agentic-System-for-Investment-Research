import json
import threading
import time

import pytest
from fake_llm import FakeClient, reply, resubmit
from fastapi.testclient import TestClient
from sec_files import make_context

from research_assistant import cli
from research_assistant.api import create_app

REPORT = {"summary": [{"text": "Apple Inc. files annual reports with the SEC.", "citations": ["company-0000320193"]}]}
FIND_APPLE = reply(tool_calls=[("find_company", {"query": "AAPL"})])
MINOR_OBJECTION = {"id": "objection-1", "claim": "claim-1", "version": 1, "where": "key_numbers[0]",
                   "issue": "unsupported_inference", "material": False, "problem": "Item 7 has no such line.",
                   "outcome": "unresolved", "notes": ["Minor, so not sent back to the team."]}


@pytest.fixture
def web(tmp_path, monkeypatch):
    """The web app with a scripted model and the SEC fixtures: set `web.model` before starting a run."""
    monkeypatch.setenv("RESEARCH_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("RESEARCH_MODEL_PROVIDER", "openrouter")
    monkeypatch.setenv("RESEARCH_MODEL", "fake-model")
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    monkeypatch.setattr(cli, "sec_client", lambda: make_context(tmp_path).sec)
    monkeypatch.setattr(cli, "model_client", lambda settings: web.model)
    with TestClient(create_app(tmp_path), base_url="http://localhost:8000") as web:
        web.traces, web.model = tmp_path / "traces", FakeClient()
        yield web


def start(web, question="Who is Apple?", **body) -> str:
    response = web.post("/api/agent-runs", json={"question": question, **body})
    assert response.status_code == 202, response.text
    assert response.json()["status"] in ("running", "finished")
    return response.json()["run_id"]


def wait(web, run_id) -> dict:
    for _ in range(500):
        run = web.get(f"/api/agent-runs/{run_id}").json()
        if run["status"] not in ("running", "stopping"):
            return run
        time.sleep(0.01)
    pytest.fail("The run did not end")


def test_a_question_runs_in_the_background_and_its_report_reopens_from_history(web):
    web.model = FakeClient(reply("1. find_company"), FIND_APPLE, reply(tool_calls=[("submit_report", REPORT)]),
                           resubmit)
    run_id = start(web, "  Who is Apple?  ", condition="B")
    run = wait(web, run_id)
    assert run["status"] == "finished" and run["question"] == "Who is Apple?"
    assert run["condition"] == "B (single agent)" and run["totals"]["model_calls"] == 4
    lines = [line["text"].removeprefix("[single_agent] ") for line in run["progress"]]
    assert lines[:3] == ["plan ready", "step 1: model asks for find_company", "step 1: find_company -> ok"]
    assert "checker: 0 flags" in lines and (web.traces / f"{run_id}.jsonl").is_file()

    [saved] = web.get("/api/agent-runs").json()["items"]
    assert saved["run_id"] == run_id and saved["status"] == "finished"
    report = web.get(f"/api/agent-runs/{run_id}/report").json()
    summary, key_numbers = report["sections"][:2]
    assert summary == {"key": "summary", "heading": "Summary", "status": "cited", "claims": [
        {"text": "Apple Inc. files annual reports with the SEC.", "status": "cited", "citations": [1], "flags": []}]}
    assert key_numbers["status"] == "abstained" and key_numbers["claims"] == []
    [source] = report["sources"]
    assert source["n"] == 1 and source["id"] == "company-0000320193" and source["text"].startswith("Apple Inc.")
    assert report["status_label"] == "finished" and report["markdown"].startswith("# Who is Apple?")


def test_the_default_condition_is_the_team_with_its_critic(web, monkeypatch):
    asked = []

    def team_with_critic(question, client, settings, context, trace):
        asked.append(question)
        trace.write("run_start", question=question, condition="D (analyst team + critic)")
        trace.write("run_end", status="finished")

    monkeypatch.setitem(cli.CONDITIONS, "D", team_with_critic)
    run = wait(web, start(web))
    assert asked == ["Who is Apple?"] and run["condition"] == "D (analyst team + critic)"


def test_cancel_ends_the_run_as_a_partial_report_marked_stopped(web):
    asking, release = threading.Event(), threading.Event()

    def slow(messages):  # holds the model call open until the test has cancelled
        asking.set()
        assert release.wait(5)
        return FIND_APPLE

    web.model = FakeClient(reply("1. find_company"), slow)
    run_id = start(web, condition="B")
    assert asking.wait(5)
    assert web.get(f"/api/agent-runs/{run_id}/report").status_code == 409  # no report while it runs
    cancelled = web.post(f"/api/agent-runs/{run_id}/cancel", json={})
    assert cancelled.status_code == 200 and cancelled.json()["status"] == "stopping"
    release.set()
    run = wait(web, run_id)
    assert run["status"] == "stopped" and run["progress"][-1]["text"] == "[single_agent] cancelled"
    report = web.get(f"/api/agent-runs/{run_id}/report").json()
    assert report["status_label"] == "stopped: the run was cancelled, so this report is partial"
    assert report["error"] is None and {s["status"] for s in report["sections"]} == {"abstained"}
    assert web.post(f"/api/agent-runs/{run_id}/cancel", json={}).status_code == 409  # nothing left to cancel


def test_a_crash_still_ends_the_trace_as_failed(web, monkeypatch):
    def broken(*args, **kwargs):
        raise RuntimeError("a bug")

    monkeypatch.setitem(cli.CONDITIONS, "B", broken)
    run = wait(web, start(web, condition="B"))
    assert run["status"] == "failed" and run["question"] == "Who is Apple?"
    assert web.get(f"/api/agent-runs/{run['run_id']}/report").json()["error"] == "RuntimeError: a bug"


def test_missing_model_settings_start_nothing_and_say_what_to_set(web, monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY")
    response = web.post("/api/agent-runs", json={"question": "Who is Apple?"})
    assert response.status_code == 409 and "API key" in response.json()["error"]["message"]
    assert web.post("/api/agent-runs", json={"question": "   "}).status_code == 422
    assert web.get("/api/agent-runs").json() == {"items": []}


def test_saved_traces_reopen_even_when_unfinished_or_markdown_only(web):
    web.traces.mkdir()
    events = {"20261103-130000-aaaaaa": [{"kind": "run_start", "question": "Find tech."},
                                         {"kind": "run_end", "status": "finished", "markdown": "# Find tech.\n",
                                          "objections": [MINOR_OBJECTION]}],
              "20261103-120000-bbbbbb": [{"kind": "run_start", "question": "Cut off."}, {"kind": "plan"}]}
    for run_id, lines in events.items():
        (web.traces / f"{run_id}.jsonl").write_text("".join(json.dumps(e) + "\n" for e in lines), encoding="utf-8")
    (web.traces / "notes.jsonl").write_text("{}\n", encoding="utf-8")  # not a run ID, so not listed
    items = web.get("/api/agent-runs").json()["items"]
    assert [(i["run_id"], i["status"]) for i in items] == [("20261103-130000-aaaaaa", "finished"),
                                                           ("20261103-120000-bbbbbb", "incomplete")]
    discover = web.get("/api/agent-runs/20261103-130000-aaaaaa/report").json()
    assert discover["sections"] == [] and discover["markdown"] == "# Find tech.\n"
    [objection] = discover["objections"]  # shown with what its issue type means and why it stayed open
    assert objection["issue"] == "unsupported inference" and objection["where"] == "key_numbers[0]"
    assert objection["meaning"].startswith("the cited evidence doesn't support the statement")
    assert objection["notes"] == ["Minor, so not sent back to the team."]
    assert web.get("/api/agent-runs/20261103-120000-bbbbbb/report").status_code == 409
    assert web.get("/api/agent-runs/20261103-120000-bbbbbb").json()["progress"] == [
        {"seq": None, "at": None, "text": "plan ready"}]
    assert web.get("/api/agent-runs/notes").status_code == 404
    assert web.get("/api/agent-runs/..%2Fresearch").status_code == 404
