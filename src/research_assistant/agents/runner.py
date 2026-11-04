"""One research run, shared by evaluation conditions B, C and D (REFERENCE §7):
plan → the lead role's tool loop → draft → deterministic checker → self-review pass(es) → [review] → report.
In B the lead is a single agent with every tool; in C it is the coordinator, whose tools include the three
analysts (team.py); D adds the critic's review and the team's revisions (critic.py). Nothing here raises on model or tool trouble; the run ends finished, stopped at limit,
stopped (cancelled) or failed, with its trace saved."""
from dataclasses import asdict, dataclass, field
from functools import partial
from pathlib import Path
from typing import Callable

from openai import OpenAIError

from .. import config
from ..model_access import ModelSettings, safe_model_error
from ..tools.result import Tool, ToolContext
from . import prompts
from .checker import CheckedReport, check
from .claims import ClaimLedger, report_claims
from .draft import SECTIONS, Draft
from .loop import Finish, LoopResult, create, run_loop, toolset
from .objections import claims_view, evidence_view, issue_list
from .report import render
from .roles import Role
from .trace import Trace

SUBMIT = Finish("submit_report", "Hand in the finished report. Every number is a {fact:ID} or {calc:ID} placeholder "
                "and every claim cites the record IDs it rests on.", Draft)


@dataclass
class AgentRun:
    run_id: str
    status: str  # finished | stopped_at_limit | stopped | failed
    plan: str | None
    report: CheckedReport
    markdown: str
    trace_path: Path
    totals: dict
    error: str | None = None


@dataclass
class Work:
    """What the lead role got done, however far it got."""

    status: str = "failed"
    plan: str | None = None
    draft: Draft | None = None
    report: CheckedReport | None = None
    error: str | None = None
    notes: list[str] = field(default_factory=list)
    # Continues the lead's conversation with another finish tool and step guard (the critic's revisions).
    resume: Callable[[Finish, int], LoopResult] | None = None
    messages: list[dict] = field(default_factory=list)  # that conversation, to add a request to before resuming
    objections: list[dict] = field(default_factory=list)  # the critic's objections and their outcomes (D)


def research(question: str, client, settings: ModelSettings, context: ToolContext, lead: Role, trace: Trace, *,
             condition: str, extra_tools: tuple[Tool, ...] = (), ledger: ClaimLedger | None = None,
             team: list[str] | None = None, max_steps: int = config.AGENT_MAX_STEPS,
             self_review_passes: int = config.AGENT_SELF_REVIEW_PASSES,
             review: Callable[[Work], None] | None = None) -> AgentRun:
    """`extra_tools` are tools the host adds to the lead's registry tools (the analysts); `team` is a list
    they fill with one line per request, shown in the report. `review` gets the finished work and may revise it
    (condition D's critic)."""
    ledger = ledger or ClaimLedger()
    trace.write("run_start", question=question, cutoff=context.cutoff.isoformat(), historical=context.historical,
                condition=condition, lead=lead.name, provider=settings.provider, model=settings.model,
                max_steps=max_steps)
    with trace.acting_as(lead.name):
        work = _work(question, client, settings, context, lead, trace, ledger, extra_tools, max_steps,
                     self_review_passes)
        if review and work.draft is not None and work.status not in ("failed", "stopped"):
            review(work)
    if context.stop.is_set():  # cancelled: what got done is the partial result, never an error
        work.status = "stopped"
    return close(trace, question, settings, context, ledger, work, condition, team)


def _work(question, client, settings, context, lead, trace, ledger, extra_tools, max_steps, passes) -> Work:
    work, cutoff = Work(), context.cutoff.isoformat()
    kwargs = settings.request_kwargs(fallbacks=True)  # no output-token cap (PROJECT_GUIDE §5)
    try:
        work.plan = _plan(question, client, settings.model, kwargs, cutoff, trace, lead, extra_tools)
    except (OpenAIError, TimeoutError) as exc:
        work.error = str(safe_model_error(exc))
        trace.write("error", step=0, error=work.error, type=type(exc).__name__)
        return work
    messages = [{"role": "system", "content": prompts.role(lead.name, cutoff)},
                {"role": "user", "content": f"{question}\n\nYour plan:\n{work.plan or '(no plan)'}"}]
    work.messages = messages
    work.resume = partial(run_loop, client, settings.model, kwargs, messages, context, trace=trace,
                          tool_names=lead.tools, extra_tools=extra_tools)
    result = work.resume(SUBMIT, max_steps=max_steps)
    steps, work.status, work.error, work.draft = result.steps, result.status, result.error, result.output
    work.report = check_draft(work.draft, context, trace, ledger, lead.name)
    # REFERENCE §7: the first pass always runs and looks for the critic's issue types, not only checker flags, so
    # B (and C) get the same kind of review D's critic gives; a further pass runs only while the checker still flags.
    for review in range(1, passes + 1):
        if not (work.report and (review == 1 or work.report.flags) and work.status == "finished" and steps < max_steps):
            break
        trace.write("self_review", review=review, flags=len(work.report.flags))
        messages.append({"role": "user", "content": _review_request(work.report, ledger, context.records)})
        again = work.resume(SUBMIT, max_steps=max_steps - steps)
        steps += again.steps
        if again.output is None:
            work.notes.append(f"The self-review pass ended without a new report ({again.error or again.status}); "
                              "the draft before it is shown" + (" with its checker flags." if work.report.flags else "."))
            break
        work.draft, work.status = again.output, again.status
        work.report = check_draft(work.draft, context, trace, ledger, lead.name)
    return work


def _plan(question, client, model, kwargs, cutoff, trace, lead: Role, extra_tools) -> str:
    """One call without tools: a short plan that the lead's loop then follows."""
    tools = "\n".join(f"- {tool.name}: {tool.description}" for tool in toolset(lead.tools, extra_tools).values())
    messages = [{"role": "system", "content": prompts.load(lead.plan_prompt, cutoff=cutoff, tools=tools)},
                {"role": "user", "content": question}]
    response = create(client, model=model, messages=messages, **kwargs)
    plan = ((response.choices[0].message.content if response.choices else None) or "").strip()
    trace.write("plan", plan=plan, model=response.model, provider=(response.model_extra or {}).get("provider"),
                usage=response.usage.model_dump() if response.usage else None)
    return plan


def check_draft(draft: Draft | None, context, trace, ledger: ClaimLedger, author: str) -> CheckedReport | None:
    if draft is None:
        return None
    report = check(draft, context.records)
    changes = ledger.stamp(author, report_claims(draft, report))
    trace.write("check", flags=[asdict(flag) for flag in report.flags], sources=len(report.sources), claims=changes)
    return report


def _review_request(report: CheckedReport, ledger: ClaimLedger, records: dict[str, dict]) -> str:
    claims = {f"{key}[{i}]": claim for key, items in report.sections.items() for i, claim in enumerate(items)}
    lines = []
    for flag in report.flags:
        claim = claims.get(flag.where)
        line = f"- {flag.where}" + (f" ({claim.id})" if claim and claim.id else "") + f": {flag.problem}"
        # Live check 3 Nov 2026: the coordinator kept analysts' claim IDs but not their citations, then resubmitted
        # the same uncited claims. Naming the citations the earlier version had makes the fix concrete.
        if claim and not claim.citations and (earlier := ledger.earlier_citations(claim.id)):
            line += (f" Its earlier version cited {', '.join(earlier)}; the claim ID in `id` doesn't cite them, so "
                     "put the ones that back this statement in its citations.")
        lines.append(line)
    flags = ("\n\nThe checker also found these problems:\n" + "\n".join(lines)) if lines else ""
    return ("Review your report before it is final. Check every statement against the evidence it cites for these "
            f"problems, the ones a critic would look for:\n{issue_list()}{flags}\n\nYour report's claims (ID, version, "
            f"where, kind, materiality), as they read with the numbers filled in:\n{claims_view(report)}\n\nThe "
            f"evidence they cite:\n{evidence_view(report.sources, records)}\n\nFix what you find and call "
            "submit_report again with the complete report (every section), unchanged if nothing needs fixing. Put a "
            "revised statement's claim ID in its `id`, so the change is recorded as a new version of that claim. You "
            "may call tools first, e.g. calculate for a figure you typed or get_financials for the right fiscal year. "
            "Remove any statement the evidence doesn't support.")


def close(trace, question, settings, context, ledger, work: Work, condition, team) -> AgentRun:
    """Render the report and write run_end: the end of every run, however far it got."""
    report, notes = work.report, list(work.notes)
    if report is None:  # no draft at all: the best partial result is the evidence gathered so far
        report = check(Draft(), context.records)
        report.sources = list(context.records)
        notes = [f"The model did not hand in a report ({work.error or work.status}). Every section is abstained; "
                 f"the {len(context.records)} records gathered before it stopped are listed as sources."] + notes
    report.limitations += notes
    model = settings.model + (f" (served by {', '.join(trace.hosts)})" if trace.hosts else "")
    markdown = render(report, context.records, question=question, status=work.status,
                      cutoff=context.cutoff.isoformat(), model=model, plan=work.plan, run_id=trace.run_id,
                      error=work.error, condition=condition, team=team, objections=work.objections)
    trace.write("run_end", status=work.status, error=work.error, totals=dict(trace.totals), by_agent=trace.by_agent,
                statuses={key: report.section_status(key) for key, _ in SECTIONS}, report=asdict(report),
                claims=ledger.versions, withdrawn=ledger.withdrawn, objections=work.objections,
                draft=work.draft.model_dump(mode="json") if work.draft else None,
                markdown=markdown)
    return AgentRun(trace.run_id, work.status, work.plan, report, markdown, trace.path, dict(trace.totals), work.error)
