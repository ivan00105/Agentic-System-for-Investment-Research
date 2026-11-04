"""eval/score.py on small hand-written traces: the gold-matching rules, behaviour, the critic's fixes and the tables."""
import json
from dataclasses import asdict
from datetime import date, datetime, timezone
from decimal import Decimal

import pytest
import score
import score_tables

from research_assistant.agents.checker import check
from research_assistant.agents.draft import Draft
from research_assistant.tools import calculate
from research_assistant.tools.result import ToolContext

FY25 = {"id": "fact-rev25", "kind": "fact", "cik": "0000320193", "metric": "revenue", "unit": "USD",
        "value": "416161000000", "start": "2024-09-29", "end": "2025-09-27"}
FY24 = {**FY25, "id": "fact-rev24", "value": "391035000000", "start": "2023-10-01", "end": "2024-09-28"}
GROWTH = calculate.run(calculate.CalculateInput(formula="growth", inputs={"current": "fact-rev25", "previous": "fact-rev24"}),
                       ToolContext(cutoff=datetime(2026, 11, 1, tzinfo=timezone.utc), sec=None,
                                   records={"fact-rev25": FY25, "fact-rev24": FY24})).data
RECORDS = {r["id"]: r for r in (FY25, FY24, GROWTH)}
FINAL = {"summary": [{"text": f"Apple's revenue grew {{calc:{GROWTH['id']}}} in fiscal 2025.", "kind": "calculation",
                      "materiality": "central"}],
         "key_numbers": [{"text": "Revenue was {fact:fact-rev25} in fiscal 2025.", "kind": "fact"}],
         "risks": [{"text": "Demand may slow.", "kind": "interpretation"}]}
CASE = {"id": "dev-aapl", "question": "How much did Apple's revenue grow in fiscal 2025?", "mode": "check",
        "companies": [{"ticker": "AAPL", "cik": 320193, "name": "Apple Inc."}],
        "expected": {"behaviour": "answer", "must_mention": ["The fiscal year ends 27 September 2025."]},
        "gold": [{"name": "revenue_fy2025", "ticker": "AAPL", "value": 416161, "unit": "USD millions",
                  "period_end": date(2025, 9, 27)},
                 {"name": "growth_fy2025", "ticker": "AAPL", "value": 6.4, "unit": "percent",
                  "period_end": date(2025, 9, 27), "tolerance": 0.05}]}


def trace(path, condition="B", draft=FINAL, status="finished", first=None, objections=(), cost=0.01,
          records=RECORDS):
    """A trace in the runner's format, its report filled by the real checker so the offline recheck agrees."""
    lead = "single" if condition == "B" else "coordinator"
    events = [{"seq": 1, "at": "2026-11-04T10:00:00+00:00", "kind": "run_start", "question": CASE["question"],
               "cutoff": "2026-11-01T23:59:59+00:00", "condition": condition, "lead": lead},
              {"seq": 2, "kind": "tool_call", "name": "get_financials", "records": records}]
    if first is not None:
        events += [{"seq": 3, "kind": "finish", "agent": lead, "valid": True, "output": first},
                   {"seq": 4, "kind": "critic_start", "agent": "critic", "round": 1}]
    report = asdict(check(Draft.model_validate(draft or {}), records))
    events.append({"seq": 9, "at": "2026-11-04T10:06:00+00:00", "kind": "run_end", "status": status, "error": None,
                   "totals": {"model_calls": 4, "tool_calls": 3, "prompt_tokens": 1000, "completion_tokens": 100,
                              "total_tokens": 1100, "cached_tokens": 600, "cost": cost},
                   "report": report, "objections": list(objections), "draft": draft, "markdown": f"# {condition}\n"})
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(e) + "\n" for e in events), encoding="utf-8")


def batch(tmp_path, *runs):
    """A batch folder: each run is (condition, trace kwargs); the index points at the traces."""
    lines = []
    for n, (condition, kwargs) in enumerate(runs):
        name = f"traces/run{n}.jsonl"
        if kwargs is not None:
            trace(tmp_path / name, condition, **kwargs)
        lines.append(json.dumps({"case": CASE["id"], "condition": condition, "repeat": 1, "trace": name}))
    (tmp_path / "runs.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return score.score(tmp_path, {CASE["id"]: CASE})


def test_tolerance_is_the_cases_or_half_a_unit_in_the_last_digit():
    assert score.tolerance({"value": 1577}) == Decimal("0.5")
    assert score.tolerance({"value": 2161735.8}) == Decimal("0.05")
    assert score.tolerance({"value": 30.8, "tolerance": 0.05}) == Decimal("0.05")


@pytest.mark.parametrize("record,outcome", [
    (FY25, "correct"),
    ({**FY25, "value": "416161400000"}, "correct"),  # within half a million
    ({**FY25, "value": "416162000000"}, "missing"),
    ({**FY25, "end": "2025-06-30"}, "needs review"),  # the value, but another period end
    ({**FY25, "value": "-416161000000"}, "needs review"),  # the size with the other sign
    ({**FY25, "cik": "0000789019"}, "missing"),  # another company
    ({**FY25, "unit": "TWD"}, "missing"),
])
def test_a_gold_item_needs_the_value_company_and_period_end(record, outcome):
    assert score.judge(CASE["gold"][0], 320193, [record])["outcome"] == outcome


def test_percent_gold_matches_a_ratio_and_an_unknown_unit_needs_review():
    judged = score.judge(CASE["gold"][1], 320193, [GROWTH])
    assert judged == {"name": "growth_fy2025", "outcome": "correct", "record": GROWTH["id"], "note": None}
    odd = score.judge({**CASE["gold"][0], "unit": "barrels"}, 320193, [FY25])
    assert odd["outcome"] == "needs review" and "barrels" in odd["note"]


def test_a_b_run_with_every_gold_figure_passes_and_rechecks_offline(tmp_path):
    [row] = batch(tmp_path, ("B", {}))
    assert row["status"] == "finished" and row["passed"] and row["answered"] and row["behaviour_ok"]
    assert [g["outcome"] for g in row["gold"]] == ["correct", "correct"] and row["recheck"] == []
    assert row["support"] == {"claims": 3, "cited": 2, "uncited": 1, "central": 1, "abstained": 3}
    assert row["minutes"] == 6.0 and row["review"] == ["Must mention: The fiscal year ends 27 September 2025."]


def test_typed_figures_and_a_missing_figure_fail_the_run(tmp_path):
    draft = {"summary": [{"text": "Revenue grew 6.4% to {fact:fact-rev25}.", "citations": ["fact-rev25"]}]}
    [row] = batch(tmp_path, ("B", {"draft": draft}))
    assert [g["outcome"] for g in row["gold"]] == ["correct", "missing"] and not row["passed"]
    assert score_tables.problems(row) == ["growth_fy2025: missing"]


@pytest.mark.parametrize("behaviour,draft,ok,passed", [
    ("not_available", {"summary": [{"text": "No company has that ticker.", "citations": ["fact-rev25"]}]}, True, True),
    ("not_available", FINAL, False, False),
    ("answer_or_abstain", {}, True, True),
    ("answer", {}, False, False),
])
def test_behaviour_follows_whether_the_report_shows_a_number(tmp_path, monkeypatch, behaviour, draft, ok, passed):
    gold = [] if behaviour == "not_available" else CASE["gold"]
    monkeypatch.setitem(CASE, "expected", {"behaviour": behaviour})
    monkeypatch.setitem(CASE, "gold", gold)
    [row] = batch(tmp_path, ("B", {"draft": draft}))
    assert (row["behaviour_ok"], row["passed"]) == (ok, passed)


def test_a_run_whose_tools_found_nothing_has_nothing_to_recheck(tmp_path, monkeypatch):
    monkeypatch.setitem(CASE, "expected", {"behaviour": "not_available"})
    monkeypatch.setitem(CASE, "gold", [])
    [row] = batch(tmp_path, ("B", {"draft": {}, "records": {}}))
    assert row["passed"] and row["recheck"] == [] and score_tables.problems(row) == []


def test_a_crashed_run_counts_its_gold_as_missing(tmp_path):
    [row] = batch(tmp_path, ("C", None))
    assert row["status"] == "crashed" and not row["passed"]
    assert [g["outcome"] for g in row["gold"]] == ["missing", "missing"]
    assert score_tables.problems(row)[0].startswith("crashed: The trace has no run_end")


def test_the_latest_index_line_wins(tmp_path):
    trace(tmp_path / "traces/new.jsonl")
    lines = [{"case": "x", "condition": "B", "repeat": 1, "trace": "traces/old.jsonl"},
             {"case": "x", "condition": "B", "repeat": 1, "trace": "traces/new.jsonl", "injected": 2}]
    (tmp_path / "runs.jsonl").write_text("".join(json.dumps(line) + "\n" for line in lines), encoding="utf-8")
    assert score.read_index(tmp_path) == [lines[1]]


def test_the_critic_table_counts_fixes_against_the_first_draft_and_the_c_run(tmp_path):
    first = {"key_numbers": FINAL["key_numbers"]}  # the growth figure is missing before the critic
    objections = [{"id": "objection-1", "issue": "missing_material_risk", "material": True, "outcome": "corrected"}]
    rows = batch(tmp_path, ("C", {"draft": first}), ("D", {"first": first, "objections": objections}))
    d = rows[1]
    assert [g["outcome"] for g in d["gold_before"]] == ["correct", "missing"] and d["passed"]
    table = score_tables.critic(rows)
    assert "| dev-aapl | 1 | 1 | 0 | 1 | 0 | 0 | 1 | 0 | 1 | 0 |" in table
    assert "(1 objections in 1 runs)" in table


def test_write_saves_the_tables_rows_and_each_report(tmp_path):
    rows = batch(tmp_path, ("B", {}), ("C", {"cost": 0.03}))
    text = score.write(tmp_path, rows, {CASE["id"]: CASE})
    for heading in ("## Accuracy", "## Support", "## Critic: fixes vs damage (D vs C)", "## Cost, tokens and latency",
                    "## Failures", "## Needs review"):
        assert heading in text
    assert "| B | 1 | 4 | 3 | 1,000 | 60% | 100 | $0.0100 | $0.0100 | 6.0 | 6.0 |" in text
    assert "| B | 1 | 1/1 (100%) | 2/2 (100%) | 1/1 (100%) | 1 |" in text
    assert "- Must mention: The fiscal year ends 27 September 2025." in text and "reports/dev-aapl--C1.md" in text
    assert (tmp_path / "scores.md").read_text(encoding="utf-8") == text
    assert len(json.loads((tmp_path / "scores.json").read_text(encoding="utf-8"))) == 2
    assert (tmp_path / "reports" / "dev-aapl--B1.md").read_text(encoding="utf-8") == "# B\n"


def test_score_main_needs_a_batch_folder(tmp_path, capsys):
    assert score.main([str(tmp_path)]) == 2
    assert "no runs.jsonl" in capsys.readouterr().err


def test_typed_numbers_count_as_answering_so_they_fail_not_available(tmp_path, monkeypatch):
    # Codex review: a report that typed its figures instead of using placeholders counted as not answering.
    monkeypatch.setitem(CASE, "expected", {"behaviour": "not_available"})
    monkeypatch.setitem(CASE, "gold", [])
    draft = {"summary": [{"text": "QZXV made $12 billion last year.", "citations": ["fact-rev25"]}]}
    [row] = batch(tmp_path, ("B", {"draft": draft}))
    assert row["answered"] and not row["behaviour_ok"] and not row["passed"]


def test_a_typed_count_in_the_limitations_is_no_answer(tmp_path, monkeypatch):
    monkeypatch.setitem(CASE, "expected", {"behaviour": "not_available"})
    monkeypatch.setitem(CASE, "gold", [])
    draft = {"summary": [{"text": "No SEC filer has that ticker.", "citations": ["fact-rev25"]}],
             "limitations": ["Searched 2 lists of tickers."]}
    [row] = batch(tmp_path, ("B", {"draft": draft}))
    assert not row["answered"] and row["passed"]


def test_an_unresolved_placeholder_needs_review(tmp_path):
    draft = {**FINAL, "bull_case": [{"text": "Margins reached {calc:calc-gone}.", "citations": ["fact-rev25"]}]}
    [row] = batch(tmp_path, ("B", {"draft": draft}))
    assert "Unresolved placeholder in bull_case[0]: {calc:calc-gone}" in row["review"]
