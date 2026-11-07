"""History in the web app: runs nested under the run that started them."""
import json

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

