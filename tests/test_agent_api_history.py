"""History in the web app: runs nested under the run that started them, and rename, archive and delete."""
import json
import threading

from fake_llm import FakeClient, reply, resubmit
from test_agent_api import start, wait

DISCOVER, PICK, OTHER = "20261107-100000-aaaaaa", "20261107-100100-bbbbbb", "20261107-120000-dddddd"
BRIEF = ("Explain whether Apple Inc. (AAPL, CIK 0000320193) fits this request, and where it doesn't: \"Find tech.\""
         "\n\nIt is shortlist pick 1 of the 1 asked for.")


def write(web, run_id, *events):
    web.traces.mkdir(exist_ok=True)
    (web.traces / f"{run_id}.jsonl").write_text("".join(json.dumps(e) + "\n" for e in events), encoding="utf-8")


def saved_runs(web):
    write(web, DISCOVER, {"kind": "run_start", "question": "Find tech."},
          {"kind": "run_end", "status": "finished", "candidates": [{"rank": 1, "run_id": PICK}]})
    write(web, PICK, {"kind": "run_start", "question": BRIEF}, {"kind": "run_end", "status": "finished"})
    write(web, OTHER, {"kind": "run_start", "question": "Who is Apple?"}, {"kind": "run_end", "status": "finished"})


def test_compare_these_starts_a_run_nested_under_its_discover_run(web):
    saved_runs(web)
    web.model = FakeClient(reply("1. find_company"), reply(tool_calls=[("find_company", {"query": "AAPL"})]),
                           reply(tool_calls=[("submit_report", {"limitations": ["Only the company record."]})]),
                           resubmit)
    run_id = start(web, "Compare Apple and Microsoft.", condition="B", parent_run_id=DISCOVER)
    assert wait(web, run_id)["parent_run_id"] == DISCOVER
    first = json.loads((web.traces / f"{run_id}.jsonl").read_text(encoding="utf-8").splitlines()[0])
    assert first["kind"] == "run_start" and first["parent_run_id"] == DISCOVER
    items = web.get("/api/agent-runs").json()["items"]
    assert [i["run_id"] for i in items] == [OTHER, DISCOVER]  # children aren't listed at the top
    assert [(c["run_id"], c["kind"], c["title"], c["status"]) for c in items[1]["children"]] == [
        (PICK, "pick", "Pick 1 of 1: Apple Inc. (AAPL)", "finished"),
        (run_id, "comparison", "Compare Apple and Microsoft.", "finished")]
    refused = web.post("/api/agent-runs", json={"question": "Compare.", "parent_run_id": "../traces"})
    assert refused.status_code == 422


def test_rename_and_archive_a_run_without_touching_its_trace(web):
    saved_runs(web)
    trace = (web.traces / f"{DISCOVER}.jsonl").read_bytes()
    renamed = web.patch(f"/api/agent-runs/{DISCOVER}", json={"label": "  Tech screen  "}).json()
    assert (renamed["title"], renamed["label"], renamed["question"]) == ("Tech screen", "Tech screen", "Find tech.")
    assert web.patch(f"/api/agent-runs/{DISCOVER}", json={"archived": True}).json()["archived"] is True
    assert [i["run_id"] for i in web.get("/api/agent-runs").json()["items"]] == [OTHER]
    [archived] = web.get("/api/agent-runs?archived=true").json()["items"]
    assert archived["title"] == "Tech screen" and [c["run_id"] for c in archived["children"]] == [PICK]
    restored = web.patch(f"/api/agent-runs/{DISCOVER}", json={"archived": False, "label": None}).json()
    assert (restored["archived"], restored["title"]) == (False, "Find tech.")
    assert (web.traces / f"{DISCOVER}.jsonl").read_bytes() == trace and json.loads(
        (web.traces / "labels.json").read_text(encoding="utf-8")) == {}
    assert web.patch(f"/api/agent-runs/{DISCOVER}", json={"label": "x" * 121}).status_code == 422
    assert web.patch("/api/agent-runs/20261107-000000-ffffff", json={"label": "x"}).status_code == 404


def test_unreadable_labels_still_list_runs_but_are_never_overwritten(web):
    saved_runs(web)
    (web.traces / "labels.json").write_text("{not json", encoding="utf-8")
    assert len(web.get("/api/agent-runs").json()["items"]) == 2
    refused = web.patch(f"/api/agent-runs/{OTHER}", json={"label": "Mine"})
    assert refused.status_code == 409 and "labels.json" in refused.json()["error"]["message"]
    assert (web.traces / "labels.json").read_text(encoding="utf-8") == "{not json"


def test_delete_a_parent_alone_or_with_its_children(web):
    saved_runs(web)
    web.patch(f"/api/agent-runs/{DISCOVER}", json={"label": "Gone soon"})
    assert web.delete(f"/api/agent-runs/{DISCOVER}").json() == {"deleted": [DISCOVER]}
    items = web.get("/api/agent-runs").json()["items"]  # its pick stays, now on its own
    assert [i["run_id"] for i in items] == [OTHER, PICK]
    assert json.loads((web.traces / "labels.json").read_text(encoding="utf-8")) == {}
    assert web.get(f"/api/agent-runs/{DISCOVER}").status_code == 404

    saved_runs(web)
    assert web.delete(f"/api/agent-runs/{DISCOVER}?children=true").json() == {"deleted": [DISCOVER, PICK]}
    assert [i["run_id"] for i in web.get("/api/agent-runs").json()["items"]] == [OTHER]
    assert web.delete(f"/api/agent-runs/{DISCOVER}").status_code == 404


def test_a_run_still_going_cannot_be_deleted(web):
    saved_runs(web)
    runs = web.app.state.agent_runs
    with runs.lock:
        runs.waiting[PICK] = None  # e.g. a pick still running under its Discover run
    refused = web.delete(f"/api/agent-runs/{DISCOVER}?children=true")
    assert refused.status_code == 409 and "Cancel it" in refused.json()["error"]["message"]
    assert (web.traces / f"{DISCOVER}.jsonl").is_file() and (web.traces / f"{PICK}.jsonl").is_file()


def test_a_pick_of_a_running_discover_run_shows_running_and_cannot_be_deleted(web):
    # Codex review: picks run on the parent's thread, so they're never in `active`; deleting one lost its events.
    write(web, DISCOVER, {"kind": "run_start", "question": "Find tech."})
    write(web, PICK, {"kind": "run_start", "question": BRIEF, "parent_run_id": DISCOVER})
    trace = (web.traces / f"{PICK}.jsonl").read_bytes()
    runs = web.app.state.agent_runs
    with runs.lock:
        runs.active[DISCOVER] = threading.Event()
    assert web.get(f"/api/agent-runs/{PICK}").json()["status"] == "running"
    assert web.get("/api/agent-runs").json()["items"][0]["children"][0]["status"] == "running"
    refused = web.delete(f"/api/agent-runs/{PICK}")
    assert refused.status_code == 409 and (web.traces / f"{PICK}.jsonl").read_bytes() == trace
    runs.active[DISCOVER].set()  # cancelled: the pick stops with it
    assert web.get(f"/api/agent-runs/{PICK}").json()["status"] == "stopping"
    with runs.lock:
        del runs.active[DISCOVER]
    assert web.get(f"/api/agent-runs/{PICK}").json()["status"] == "incomplete"
