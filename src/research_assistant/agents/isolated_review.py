"""REFERENCE §7's isolated review test: condition D's critic and revisions on a saved run's final draft and frozen
evidence, so a review starts from the same draft whatever the team retrieved. Optionally a labelled test defect is
injected first (evidence.inject_wrong_period); the trace records it as its own claim version, written by "injected".

The coordinator and the analysts start new conversations, so their follow-ups name the companies again. Their tools
still run and may fetch (the SEC client's disk cache answers most of it); only the draft and its records are frozen.
"""
import copy
from datetime import datetime
from functools import partial
from pathlib import Path
from typing import Callable

from .. import config
from ..data.sec import SecClient
from ..model_access import ModelSettings
from ..tools.result import ToolContext
from . import evidence, prompts
from .claims import ClaimLedger
from .critic import Critic
from .draft import Draft
from .loop import run_loop
from .objections import draft_with_ids
from .roles import COORDINATOR
from .runner import AgentRun, Work, check_draft, close
from .team import Desk
from .trace import Trace

DEFECTS = {"wrong_period": evidence.inject_wrong_period}


class NotReviewable(ValueError):
    """The trace has no final draft to review (it failed early, or was saved before drafts were kept)."""


def run(path: Path, client, settings: ModelSettings, sec: SecClient, *, inject: str | None = None,
        max_steps: int = config.AGENT_MAX_STEPS, critic_rounds: int = config.AGENT_CRITIC_ROUNDS,
        trace_dir: Path | None = None, echo: Callable[[dict], None] | None = None) -> AgentRun:
    saved = evidence.load(path)
    if not (saved.start and saved.end and saved.end.get("draft")):
        raise NotReviewable(f"{path} holds no final draft to review.")
    question, cutoff = saved.start["question"], datetime.fromisoformat(saved.start["cutoff"])
    context = ToolContext(cutoff=cutoff, sec=sec, records=dict(saved.records),
                          historical=bool(saved.start.get("historical")))
    ledger = ClaimLedger()  # the saved run's claims, so every claim keeps its ID and version
    ledger.versions = copy.deepcopy(saved.end.get("claims") or {})
    ledger.latest[COORDINATOR.name] = [c["id"] for claims in saved.end["report"]["sections"].values()
                                       for c in claims if c.get("id")]
    condition = f"D review of saved run {Path(path).stem}" + (f", with an injected {inject} defect" if inject else "")
    trace = Trace.new(trace_dir, echo)
    trace.write("run_start", question=question, cutoff=cutoff.isoformat(), historical=context.historical,
                condition=condition, lead=COORDINATOR.name,
                provider=settings.provider, model=settings.model, max_steps=max_steps, reviewed=str(path))
    # The evidence it starts from, frozen here too: this trace can be rechecked or reviewed again on its own, even
    # if no tool runs during the review.
    trace.write("evidence", records=trace.new_records(context.records))
    desk = Desk(question, client, settings, trace, ledger, max_steps)
    critic = Critic(question, client, settings, context, trace, ledger, desk, max_steps, critic_rounds)
    work = Work(status="finished", draft=Draft.model_validate(saved.end["draft"]))
    with trace.acting_as(COORDINATOR.name):
        work.report = check_draft(work.draft, context, trace, ledger, COORDINATOR.name)  # every claim unchanged
        if inject:
            found = DEFECTS[inject](Draft.model_validate(draft_with_ids(work.draft, work.report)), context.records)
            if found is None:
                work.notes.append(f"No claim could take an injected {inject} defect, so the draft is as saved.")
            else:
                work.draft, change = found
                trace.write("injected", defect=inject, change=change)
                work.notes.append(f"Test defect injected before the review ({inject}): {change}")
                work.report = check_draft(work.draft, context, trace, ledger, "injected")
        work.messages = [
            {"role": "system", "content": prompts.role(COORDINATOR.name, cutoff.isoformat())},
            {"role": "user", "content": f"{question}\n\nYour team researched this question and you handed in a "
                                        "report. A critic now reviews it, and you answer its objections with your "
                                        "analysts' help. Your analysts start fresh, so give them the company's "
                                        "name, ticker and CIK again."}]
        work.resume = partial(run_loop, client, settings.model, settings.request_kwargs(fallbacks=True),
                              work.messages, context, trace=trace, tool_names=COORDINATOR.tools,
                              extra_tools=desk.tools())
        critic.review(work)
    return close(trace, question, settings, context, ledger, work, condition, desk.log)
