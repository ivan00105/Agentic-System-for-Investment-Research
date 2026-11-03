"""The analyst team, evaluation condition C (REFERENCE §2, §7). A coordinator plans, asks three specialist analysts
(fundamentals, filings and events, market and valuation) for findings, and merges them into the report.

Every role is the same loop (loop.py) with its own prompt and tools (roles.py). Each analyst is a tool in the
coordinator's loop, so the coordinator decides whom to ask, what, and whether to follow up. The analysts share
the run's records, trace and claim ledger, and every trace event names the role that wrote it.
"""
from functools import partial
from pathlib import Path
from typing import Callable

from pydantic import BaseModel, Field

from .. import config
from ..model_access import ModelSettings
from ..tools.result import Tool, ToolContext, ToolResult
from . import prompts
from .checker import check_claims, fill
from .claims import ClaimLedger
from .draft import Findings
from .loop import Finish, run_loop
from .roles import ANALYSTS, COORDINATOR, Role
from .runner import AgentRun, research
from .trace import Trace

CONDITION = "C (analyst team)"
SUBMIT_FINDINGS = Finish("submit_findings", "Hand your findings to the coordinator. Every number is a {fact:ID} or "
                         "{calc:ID} placeholder and every finding cites the record IDs it rests on.", Findings)


class AnalystTask(BaseModel):
    task: str = Field(min_length=1, description=(
        "What to find out: the companies (name, ticker and CIK), fiscal periods, metrics or filing sections, and "
        "what you need them for. Asking the same analyst again continues its earlier work."))


def run(question: str, client, settings: ModelSettings, context: ToolContext, *,
        max_steps: int = config.AGENT_MAX_STEPS, self_review_passes: int = config.AGENT_SELF_REVIEW_PASSES,
        trace_dir: Path | None = None, echo: Callable[[dict], None] | None = None) -> AgentRun:
    trace, ledger = Trace.new(trace_dir, echo), ClaimLedger()
    desk = Desk(question, client, settings, trace, ledger, max_steps)
    return research(question, client, settings, context, COORDINATOR, trace, condition=CONDITION,
                    extra_tools=desk.tools(), ledger=ledger, team=desk.log, max_steps=max_steps,
                    self_review_passes=self_review_passes)


class Desk:
    """The analysts the coordinator can ask, as tools of its loop. Each analyst keeps its own conversation, so a
    follow-up builds on its earlier work. Its findings are checked and get claim IDs, but are never rejected:
    flags go back to the coordinator, who can follow up (PROJECT_GUIDE §5 rule 6)."""

    def __init__(self, question: str, client, settings: ModelSettings, trace: Trace, ledger: ClaimLedger,
                 max_steps: int):
        self.question, self.client, self.model, self.trace, self.ledger = question, client, settings.model, trace, ledger
        self.kwargs = settings.request_kwargs(fallbacks=True)  # no output-token cap (PROJECT_GUIDE §5)
        self.max_steps = max_steps  # per request: the same guard as any other agent's loop
        self.conversations: dict[str, list[dict]] = {}
        self.log: list[str] = []  # one line per request, for the report's "Who did what"

    def tools(self) -> tuple[Tool, ...]:
        return tuple(Tool(f"ask_{role.name}", f"Ask the {role.title} analyst. {role.brief} Its tools: "
                          f"{', '.join(role.tools)}. Returns its findings (claim ID, text with placeholders, how it "
                          "reads, cited record IDs, checker flags) and its gaps.", AnalystTask, partial(self.ask, role),
                          f"{role.name} analyst") for role in ANALYSTS)

    def ask(self, role: Role, args: AnalystTask, context: ToolContext) -> ToolResult:
        follow_up = role.name in self.conversations
        if follow_up:
            messages = self.conversations[role.name]
            messages.append({"role": "user", "content": f"Follow-up from the coordinator:\n{args.task}"})
        else:
            messages = self.conversations[role.name] = [
                {"role": "system", "content": prompts.role(role.name, context.cutoff.isoformat())},
                {"role": "user", "content": f"The user's question: {self.question}\n\n"
                                            f"Your task from the coordinator:\n{args.task}"}]
        with self.trace.acting_as(role.name):
            self.trace.write("analyst_start", task=args.task, follow_up=follow_up)
            result = run_loop(self.client, self.model, self.kwargs, messages, context, SUBMIT_FINDINGS, self.trace,
                              tool_names=role.tools, max_steps=self.max_steps)
            findings = result.output or Findings()
            checked = check_claims(findings.findings, "findings", context.records)
            claims = self.ledger.stamp(role.name, [(f"findings[{i}]", claim, c) for i, (claim, c) in
                                                   enumerate(zip(findings.findings, checked, strict=True))],
                                       replaces=False)
            for c in checked:  # each finding is citable by its claim ID, which brings its own citations
                context.remember({"id": c.id, "kind": "claim", "author": role.name, "version": c.version,
                                  "text": c.text, "citations": c.citations})
            gaps = [fill(text, f"gaps[{i}]", context.records) for i, text in enumerate(findings.gaps)]
            self.trace.write("analyst_end", status=result.status, steps=result.steps, error=result.error,
                             findings=len(checked), claims=claims)
        self.log.append(f"{role.title} analyst ({result.status}, {result.steps} model calls, {len(checked)} findings): "
                        + " ".join(args.task.split()))
        warnings = [f"{flag.where}: {flag.problem}" for _, _, flags in gaps for flag in flags]
        if result.output is None:
            status = "unavailable"
            warnings.insert(0, f"The {role.title} analyst handed in no findings ({result.error or result.status}).")
        elif result.status != "finished":
            status = "partial"
            warnings.insert(0, "The analyst reached its step limit, so its findings are partial.")
        else:
            status = "ok"
        if flagged := sum(1 for c in checked if c.flags):
            warnings.append(f"{flagged} of {len(checked)} findings have checker flags (see each finding's flags).")
        data = {"analyst": role.name, "status": result.status, "model_calls": result.steps,
                "findings": [{"claim": c.id, "version": c.version, "text": claim.text, "reads": c.text,
                              "kind": claim.kind, "materiality": claim.materiality, "citations": c.citations,
                              "flags": [flag.problem for flag in c.flags]}
                             for claim, c in zip(findings.findings, checked, strict=True)],
                "gaps": [text for text, _, _ in gaps]}
        ids = list(dict.fromkeys([c.id for c in checked] + [i for c in checked for i in c.citations]))
        return ToolResult(status=status, data=data, ids=ids, source=f"{role.name} analyst", warnings=warnings)
