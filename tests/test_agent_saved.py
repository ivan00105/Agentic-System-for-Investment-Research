import json

from research_assistant.agents import saved

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
