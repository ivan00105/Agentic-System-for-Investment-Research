"""Frozen evidence: a run's trace keeps every record its tools returned, in full (facts, filing paragraphs, the
daily prices behind a calculation), so a saved run can be reopened and its numbers rechecked offline, with no
SEC, price provider or model call. Files are enough for now; SQLite waits for the UI (PROJECT_GUIDE Phase 7)."""
import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from ..tools import calculate
from ..tools.result import ToolContext
from .checker import check
from .draft import SECTIONS, Draft


@dataclass
class SavedRun:
    events: list[dict]
    records: dict[str, dict]  # every record the run's tools returned, by ID
    start: dict | None  # the run_start and run_end events, if the run got that far
    end: dict | None


@dataclass
class Recheck:
    calcs: int = 0  # calculations recomputed from their frozen inputs
    statements: int = 0  # report statements filled again from the frozen records
    problems: list[str] = field(default_factory=list)


def load(path: Path) -> SavedRun:
    events = [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines() if line.strip()]
    records: dict[str, dict] = {}
    for event in events:
        records.update(event.get("records") or {})
    start = next((e for e in events if e["kind"] == "run_start"), None)
    end = next((e for e in reversed(events) if e["kind"] == "run_end"), None)
    return SavedRun(events, records, start, end)


def recheck(path: Path) -> Recheck:
    """Recompute every calculation from the frozen records it cites and refill the final report's placeholders,
    then compare both with what the run saved. A mismatch is listed, never fixed."""
    run, outcome = load(path), Recheck()
    if not run.records:
        outcome.problems.append("The trace holds no tool records (it was saved before evidence was frozen), so "
                                "nothing could be rechecked.")
        return outcome
    cutoff = datetime.fromisoformat(run.start["cutoff"]) if run.start else datetime.now()
    context = ToolContext(cutoff=cutoff, sec=None, records=dict(run.records))  # calculate never fetches
    for record in run.records.values():
        if record.get("kind") != "calc":
            continue
        outcome.calcs += 1
        result = calculate.run(calculate.CalculateInput(formula=record["formula"], inputs=record["inputs"]), context)
        if result.status not in ("ok", "unsupported"):
            outcome.problems.append(f"{record['id']} could not be recomputed: {'; '.join(result.warnings)}")
        elif result.data["value"] != record["value"]:
            outcome.problems.append(f"{record['id']} ({record['formula']}) was saved as {record['value']} but "
                                    f"recomputes to {result.data['value']} from its frozen inputs.")
    if run.end and run.end.get("draft") is not None:
        report = check(Draft.model_validate(run.end["draft"]), run.records)
        saved = run.end["report"]["sections"]
        for key, _ in SECTIONS:
            if len(report.sections[key]) != len(saved[key]):
                outcome.problems.append(f"{key} has {len(report.sections[key])} statements in the saved draft but "
                                        f"{len(saved[key])} in the saved report.")
            for i, (claim, old) in enumerate(zip(report.sections[key], saved[key], strict=False)):
                outcome.statements += 1
                if claim.text != old["text"]:
                    outcome.problems.append(f"{key}[{i}] now reads {claim.text!r}, but the saved report has "
                                            f"{old['text']!r}.")
    return outcome
