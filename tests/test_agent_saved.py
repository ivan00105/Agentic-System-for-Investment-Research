import json

from research_assistant.agents import saved
from research_assistant.agents.discover import pick_title

FILING = {"id": "filing-1", "kind": "filing", "form": "8-K", "filed": "2026-04-20", "description": "Current report"}


def trace_with(tmp_path, record):
    path = tmp_path / "20261104-000000-abcdef.jsonl"
    events = [{"seq": 1, "kind": "run_start", "question": "Any events?", "cutoff": "2026-11-01T23:59:59+00:00"},
              {"seq": 2, "kind": "tool_call", "records": {record["id"]: record}}]
    path.write_text("".join(json.dumps(event) + "\n" for event in events), encoding="utf-8")
    return path


def test_8k_items_show_their_code_and_name(tmp_path):
    # Codex review: list_filings stores items as {code, name}, and the evidence panel's join raised TypeError.
    filing = FILING | {"items": [{"code": "5.02", "name": "Director or officer departure, election or pay"},
                                 {"code": "9.01", "name": "Financial statements and exhibits"}]}
    shown = saved.record(trace_with(tmp_path, filing), "filing-1")
    assert {"label": "8-K items", "value": "5.02 Director or officer departure, election or pay, "
                                           "9.01 Financial statements and exhibits"} in shown["rows"]


def test_8k_items_saved_as_plain_codes_still_show(tmp_path):
    shown = saved.record(trace_with(tmp_path, FILING | {"items": ["5.02", "9.01"]}), "filing-1")
    assert {"label": "8-K items", "value": "5.02, 9.01"} in shown["rows"]


DISCOVER, PICK, COMPARISON, OTHER = ("20261107-100000-aaaaaa", "20261107-100100-bbbbbb", "20261107-110000-cccccc",
                                     "20261107-120000-dddddd")
BRIEF = ("Explain whether Apple Inc. (AAPL, CIK 0000320193) fits this request, and where it doesn't: \"Find tech.\""
         "\n\nIt is shortlist pick 2 of the 5 asked for. A screen of the S&P 500 ranked it 4 by revenue.")
OLD_BRIEF = "Explain whether ADOBE INC. (ADBE, CIK 0000796343) fits this request, and where it doesn't: \"Find tech.\""


def write(folder, run_id, *events):
    (folder / f"{run_id}.jsonl").write_text("".join(json.dumps(e) + "\n" for e in events), encoding="utf-8")


def start(question, parent=None):
    return {"kind": "run_start", "question": question, **({"parent_run_id": parent} if parent else {})}


def test_history_nests_picks_and_comparisons_under_their_discover_run(tmp_path):
    write(tmp_path, DISCOVER, start("Find tech."))  # still running: no run_end lists its picks yet
    write(tmp_path, PICK, start(BRIEF, DISCOVER), {"kind": "run_end", "status": "finished"})
    write(tmp_path, COMPARISON, start("Compare Apple and Microsoft.", DISCOVER))
    write(tmp_path, OTHER, start("Who is Apple?"))
    top = saved.runs(tmp_path)
    assert [(run["run_id"], run["children"]) for run in top[:1]] == [(OTHER, [])]
    assert [run["run_id"] for run in top] == [OTHER, DISCOVER]
    pick, comparison = top[1]["children"]
    assert (pick["kind"], pick["title"], pick["question"]) == ("pick", "Pick 2 of 5: Apple Inc. (AAPL)", BRIEF)
    assert (pick["status"], pick["parent_run_id"]) == ("finished", DISCOVER)
    assert (comparison["kind"], comparison["title"]) == ("comparison", "Compare Apple and Microsoft.")


def test_old_traces_without_a_parent_link_nest_through_the_discover_run_end(tmp_path):
    candidates = [{"rank": 1, "outcome": "picked", "run_id": PICK}, {"rank": 2, "outcome": "rejected", "run_id": None},
                  {"rank": 3, "outcome": "picked", "run_id": "20261107-100500-eeeeee"}]  # its trace was deleted
    write(tmp_path, DISCOVER, start("Find tech."), {"kind": "run_end", "status": "finished", "candidates": candidates})
    write(tmp_path, PICK, start(OLD_BRIEF), {"kind": "run_end", "status": "finished"})
    [found] = saved.runs(tmp_path)
    [pick] = found["children"]
    assert (pick["run_id"], pick["parent_run_id"], pick["title"]) == (PICK, None, "Pick: ADOBE INC. (ADBE)")


def test_a_run_whose_parent_is_gone_or_newer_is_listed_on_its_own(tmp_path):
    write(tmp_path, DISCOVER, start("A", "20261107-090000-ffffff"))  # its parent was deleted
    write(tmp_path, COMPARISON, start("B", OTHER))  # a newer run can't be its parent, so links never loop
    write(tmp_path, OTHER, start("C", COMPARISON))
    top = saved.runs(tmp_path)
    assert [(run["run_id"], [c["run_id"] for c in run["children"]]) for run in top] == [
        (COMPARISON, [OTHER]), (DISCOVER, [])]


def test_a_pick_title_is_short_and_any_other_question_is_its_own_title():
    assert pick_title(BRIEF) == "Pick 2 of 5: Apple Inc. (AAPL)"
    assert pick_title(OLD_BRIEF) == "Pick: ADOBE INC. (ADBE)"  # saved before briefs gave the pick number
    assert pick_title(BRIEF.replace("AAPL", "no ticker")) == "Pick 2 of 5: Apple Inc."
    assert pick_title("Alphabet Inc. (GOOGL, GOOG, CIK 0001652044)") is None and pick_title(None) is None
    assert pick_title(BRIEF.replace("(AAPL", "(GOOGL, GOOG")) == "Pick 2 of 5: Apple Inc. (GOOGL)"


def test_a_child_started_in_the_same_second_as_its_parent_still_nests(tmp_path):
    # Codex review: whole IDs compared the random suffix too, so this child's lower suffix lost its parent.
    parent, child = "20261107-100000-ffffff", "20261107-100000-111111"
    write(tmp_path, parent, start("Find tech."))
    write(tmp_path, child, start(BRIEF, parent))
    assert [(run["run_id"], [c["run_id"] for c in run["children"]]) for run in saved.runs(tmp_path)] == [
        (parent, [child])]


def test_runs_in_the_same_second_that_name_each_other_never_loop(tmp_path):
    first, second = "20261107-100000-111111", "20261107-100000-222222"
    write(tmp_path, first, start("A", second))
    write(tmp_path, second, start("B", first))
    assert [(run["run_id"], [c["run_id"] for c in run["children"]]) for run in saved.runs(tmp_path)] == [
        (second, [first])]
