"""The single research agent, evaluation condition B (REFERENCE §7):
plan → tool loop → draft → deterministic checker → one self-review pass → report. Nothing here raises
on model or tool trouble; the run ends finished, stopped at limit or failed, with its trace saved."""
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable

from openai import OpenAIError

from .. import config
from ..model_access import ModelSettings, safe_model_error
from ..tools import registry
from ..tools.result import ToolContext
from . import prompts
from .checker import CheckedReport, check
from .draft import SECTIONS, Draft
from .loop import Finish, run_loop
from .report import render
from .trace import Trace

SUBMIT = Finish("submit_report", "Hand in the finished report. Every number is a {fact:ID} or {calc:ID} placeholder "
                "and every claim cites the record IDs it rests on.", Draft)


@dataclass
class AgentRun:
    run_id: str
    status: str  # finished | stopped_at_limit | failed
    plan: str | None
    report: CheckedReport
    markdown: str
    trace_path: Path
    totals: dict
    error: str | None = None


def run(question: str, client, settings: ModelSettings, context: ToolContext, *,
        max_steps: int = config.AGENT_MAX_STEPS, self_review_passes: int = config.AGENT_SELF_REVIEW_PASSES,
        trace_dir: Path | None = None, echo: Callable[[dict], None] | None = None) -> AgentRun:
    trace = Trace.new(trace_dir, echo)
    cutoff = context.cutoff.isoformat()
    trace.write("run_start", question=question, cutoff=cutoff, provider=settings.provider, model=settings.model,
                max_steps=max_steps)
    kwargs = settings.request_kwargs(fallbacks=True)  # no output-token cap (PROJECT_GUIDE §5)
    try:
        plan = _plan(question, client, settings.model, kwargs, cutoff, trace)
    except (OpenAIError, TimeoutError) as exc:
        error = str(safe_model_error(exc))
        trace.write("error", step=0, error=error, type=type(exc).__name__)
        return _end(trace, question, settings, context, "failed", None, None, [], error)

    messages = [{"role": "system", "content": prompts.load("single_agent", cutoff=cutoff)},
                {"role": "user", "content": f"{question}\n\nYour plan:\n{plan or '(no plan)'}"}]
    result = run_loop(client, settings.model, kwargs, messages, context, SUBMIT, trace, max_steps=max_steps)
    steps, status, error = result.steps, result.status, result.error
    report = _check(result.output, context, trace)
    notes = []
    for review in range(1, self_review_passes + 1):
        if not (report and report.flags and status == "finished" and steps < max_steps):
            break
        trace.write("self_review", review=review, flags=len(report.flags))
        messages.append({"role": "user", "content": _review_request(report)})
        again = run_loop(client, settings.model, kwargs, messages, context, SUBMIT, trace, max_steps=max_steps - steps)
        steps += again.steps
        if again.output is None:
            notes.append(f"The self-review pass ended without a new report ({again.error or again.status}); "
                         "the first draft is shown with its checker flags.")
            break
        report, status = _check(again.output, context, trace), again.status
    return _end(trace, question, settings, context, status, plan, report, notes, error)


def _plan(question, client, model, kwargs, cutoff, trace) -> str:
    """One call without tools: a short plan that the loop then follows."""
    tools = "\n".join(f"- {s['function']['name']}: {s['function']['description']}" for s in registry.schemas())
    messages = [{"role": "system", "content": prompts.load("plan", cutoff=cutoff, tools=tools)},
                {"role": "user", "content": question}]
    response = client.chat.completions.create(model=model, messages=messages, **kwargs)
    plan = ((response.choices[0].message.content if response.choices else None) or "").strip()
    trace.write("plan", plan=plan, model=response.model, provider=(response.model_extra or {}).get("provider"),
                usage=response.usage.model_dump() if response.usage else None)
    return plan


def _check(draft: Draft | None, context, trace) -> CheckedReport | None:
    if draft is None:
        return None
    report = check(draft, context.records)
    trace.write("check", flags=[asdict(flag) for flag in report.flags], sources=len(report.sources))
    return report


def _review_request(report: CheckedReport) -> str:
    flags = "\n".join(f"- {flag.where}: {flag.problem}" for flag in report.flags)
    return ("The checker found these problems in your report:\n" + flags + "\n\nFix them and call submit_report "
            "again with the complete corrected report (every section). You may call tools first, e.g. calculate "
            "for a figure you typed. Remove any statement the evidence doesn't support.")


def _end(trace, question, settings, context, status, plan, report, notes, error) -> AgentRun:
    if report is None:  # no draft at all: the best partial result is the evidence gathered so far
        report = check(Draft(), context.records)
        report.sources = list(context.records)
        notes = [f"The model did not hand in a report ({error or status}). Every section is abstained; the "
                 f"{len(context.records)} records gathered before it stopped are listed as sources."] + notes
    report.limitations += notes
    model = settings.model + (f" (served by {', '.join(trace.hosts)})" if trace.hosts else "")
    markdown = render(report, context.records, question=question, status=status, cutoff=context.cutoff.isoformat(),
                      model=model, plan=plan, run_id=trace.run_id, error=error)
    trace.write("run_end", status=status, error=error, totals=dict(trace.totals),
                statuses={key: report.section_status(key) for key, _ in SECTIONS}, report=asdict(report),
                markdown=markdown)
    return AgentRun(trace.run_id, status, plan, report, markdown, trace.path, dict(trace.totals), error)
