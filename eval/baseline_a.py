"""Condition A for the evaluation (REFERENCE §7): the old fixed pipeline (research.retrieve_company), run once per
company without its model review, so A shows what plain software already solves. Its result is written as a trace
in the same format as B-D (run_start, the records, run_end), so score.py reads every condition the same way."""
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from research_assistant.agents.draft import SECTIONS
from research_assistant.agents.trace import Trace
from research_assistant.contracts import UNIVERSE, CompanyReport, RunRequest
from research_assistant.research import retrieve_company
from research_assistant.store import Store

CONDITION = "A (fixed pipeline)"
MODES = ("check", "compare")  # the old pipeline reports companies' latest annual figures; its screen isn't Discover


def unsupported(case: dict) -> str | None:
    """Why A can't run this case, or None if it can: its five companies and check or compare questions only."""
    if case["mode"] not in MODES:
        return f"A has no {case['mode']} mode"
    outside = [c["ticker"] for c in case["companies"] if c["ticker"] not in UNIVERSE]
    return f"{', '.join(outside)} is outside A's five companies" if outside else None


def run(case: dict, cutoff: datetime, trace: Trace, store_dir: Path) -> None:
    trace.write("run_start", question=case["question"], cutoff=cutoff.isoformat(), condition=CONDITION,
                lead="pipeline", provider=None, model=None, max_steps=None)
    store = Store(store_dir)
    claims, shown, limitations, errors = [], [], [], []
    for company in case["companies"]:
        ticker = company["ticker"]
        run_id, _ = store.accept(RunRequest(mode="fresh", ticker=ticker, cutoff=cutoff, model_analysis=False),
                                 f"eval-{uuid4()}")
        try:
            report = retrieve_company(store, run_id, ticker, cutoff)
        except Exception as exc:  # DomainError for known problems, anything else is a bug; A ends failed either way
            store.update(run_id, status="failed", error=str(exc))
            errors.append(f"{ticker}: {exc}")
            trace.write("pipeline", ticker=ticker, status="failed", error=str(exc))
            continue
        store.update(run_id, status="completed")
        records = _records(report)
        trace.write("pipeline", ticker=ticker, status="ok", records=records)
        shown += list(records)
        claims += [{"text": c.statement, "kind": c.kind, "citations": c.evidence_ids, "flags": [],
                    "materiality": "central", "id": c.id, "version": c.version} for c in report.claims]
        limitations += [f"{ticker}: {line}" for line in report.limitations]
    status = "failed" if errors and not shown else "finished"
    sections = {key: claims if key == "key_numbers" else [] for key, _ in SECTIONS}
    lines = [f"# {case['question']}", f"- Condition: {CONDITION}", f"- Cutoff: {cutoff.isoformat()}",
             f"- Run status: {status}", "", "## Key numbers", *[f"- {c['text']}" for c in claims],
             "", "## Limitations", *[f"- {line}" for line in limitations + errors]]
    trace.write("run_end", status=status, error="; ".join(errors) or None, totals=dict(trace.totals), by_agent={},
                statuses={key: "cited" if sections[key] else "abstained" for key, _ in SECTIONS},
                report={"sections": sections, "limitations": limitations, "flags": [], "sources": shown},
                claims={}, withdrawn=[], objections=[], draft=None, shown=shown, markdown="\n".join(lines) + "\n")


def _records(report: CompanyReport) -> dict[str, dict]:
    """A's metrics as fact and calc records, shaped like the agents' tool records."""
    metric = {m.fact_id: m.id for m in report.metrics if m.fact_id}
    records = {}
    for fact in report.facts:
        if fact.id in metric:
            records[fact.id] = {"id": fact.id, "kind": "fact", "cik": fact.issuer_cik, "metric": metric[fact.id],
                                "tag": fact.concept, "unit": fact.unit, "value": str(fact.normalized_value),
                                "start": fact.start and fact.start.isoformat(), "end": fact.end.isoformat(),
                                "accession": fact.accession, "form": fact.form, "filed": fact.filed.isoformat()}
    for calc in report.calculations:
        inputs = [records[i] for i in calc.input_fact_ids if i in records]
        if calc.result is not None and inputs:
            records[calc.id] = {"id": calc.id, "kind": "calc", "cik": inputs[0]["cik"], "formula": calc.formula,
                                "inputs": list(calc.input_fact_ids), "value": str(calc.result), "unit": "ratio",
                                "start": inputs[0]["start"], "end": inputs[0]["end"]}
    return records
