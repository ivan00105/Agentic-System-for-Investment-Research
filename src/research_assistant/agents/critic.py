"""The critic and the revision loop, evaluation condition D (REFERENCE §3, §7): condition C's analyst team, then
up to config.AGENT_CRITIC_ROUNDS reviews by a critic, the same loop with read-only tools plus verify_against_filing.

The critic hands in objections, each tied to a claim ID and version. The coordinator routes each to the analyst that
owns the claim (a follow-up through ask_<role>, which continues that analyst's conversation) and answers with a
revised report and one outcome per objection: defended, corrected, withdrawn or unresolved. The claim ledger, not the
coordinator's word, decides whether a claim changed: a correction is a new claim version the coordinator calls
corrected and backs with a citation, a withdrawal a claim gone from the report. An objection the coordinator doesn't
settle stays open for the next round; what is still open when the review stops is shown as unresolved, never dropped.
"""
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable

from .. import config
from ..model_access import ModelSettings
from ..tools.result import ToolContext, make_id
from . import prompts
from .checker import CITATION, CheckedReport, Flag, fill, lookup, typed_numbers
from .claims import ClaimLedger
from .loop import Finish, run_loop
from .objections import Objection, Objections, Revision, claims_view, draft_with_ids, evidence_view, issue_list
from .roles import ANALYSTS, COORDINATOR, CRITIC
from .runner import AgentRun, Work, check_draft, research
from .team import Desk
from .trace import Trace

CONDITION = "D (analyst team + critic)"
SUBMIT_OBJECTIONS = Finish("submit_objections", "Hand in your objections: zero or more, each tied to a claim ID and "
                           "version, with its issue type, the records that show it and the check that would settle it.",
                           Objections)
SUBMIT_REVISION = Finish("submit_revision", "Hand in the revised report, every section, with one outcome per "
                         "objection. Every number is a {fact:ID} or {calc:ID} placeholder and every claim cites the "
                         "record IDs it rests on.", Revision)


def run(question: str, client, settings: ModelSettings, context: ToolContext, *,
        max_steps: int = config.AGENT_MAX_STEPS, self_review_passes: int = config.AGENT_SELF_REVIEW_PASSES,
        critic_rounds: int = config.AGENT_CRITIC_ROUNDS, trace_dir: Path | None = None,
        echo: Callable[[dict], None] | None = None, trace: Trace | None = None) -> AgentRun:
    """`trace` is one the host made already, so it knows the run ID before the run starts (the web app)."""
    trace, ledger = trace or Trace.new(trace_dir, echo), ClaimLedger()
    desk = Desk(question, client, settings, trace, ledger, max_steps)
    critic = Critic(question, client, settings, context, trace, ledger, desk, max_steps, critic_rounds)
    return research(question, client, settings, context, COORDINATOR, trace, condition=CONDITION,
                    extra_tools=desk.tools(), ledger=ledger, team=desk.log, max_steps=max_steps,
                    self_review_passes=self_review_passes, review=critic.review)


@dataclass
class Raised:
    """One objection and what became of it. `outcome` is "open" until the objection ends (REFERENCE §3)."""

    id: str
    round: int
    claim: str
    version: int  # the claim version it is about: a resolution on v1 does not validate v2
    where: str
    owner: str  # the analyst that wrote the claim, else the coordinator
    issue: str
    material: bool
    problem: str  # placeholders filled
    evidence: list[str]  # resolved record IDs
    requested_check: str
    outcome: str = "open"
    closed_in: int | None = None
    new_version: int | None = None  # corrected: the claim's version that answers it
    new_claims: list[str] = field(default_factory=list)  # corrected missing risk: the claims added for it
    explanation: str | None = None
    citations: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def close(self, outcome: str, closed_in: int | None, explanation: str | None = None,
              citations: list[str] = (), new_version: int | None = None):
        self.outcome, self.closed_in, self.new_version = outcome, closed_in, new_version
        self.explanation, self.citations = explanation, list(citations)


class Critic:
    def __init__(self, question: str, client, settings: ModelSettings, context: ToolContext, trace: Trace,
                 ledger: ClaimLedger, desk: Desk, max_steps: int, rounds: int):
        self.question, self.client, self.model, self.context = question, client, settings.model, context
        self.trace, self.ledger, self.desk, self.max_steps, self.rounds = trace, ledger, desk, max_steps, rounds
        self.kwargs = settings.request_kwargs(fallbacks=True)  # no output-token cap (PROJECT_GUIDE §5)
        self.raised: list[Raised] = []

    def review(self, work: Work) -> None:
        """Review, revise, review again, until no material objection is open (or the guard). Changes `work`."""
        stop = (f"Still open after the last review allowed (AGENT_CRITIC_ROUNDS = {self.rounds}), so it was not "
                "routed to the team.")
        for n in range(1, self.rounds + 1):
            if self._critique(work, n) is None:
                stop = f"Still open: the critic's review in round {n} ended without objections."
                break
            pending = [o for o in self.raised if o.outcome == "open"]
            if not any(o.material for o in pending):
                stop = "Minor, so not sent back to the team: the review stops once no material objection is left."
                break
            if n == self.rounds:
                break
            if not self._revise(work, n, pending):
                stop = f"Still open: the revision in round {n} ended without a report."
                break
        for o in self.raised:
            if o.outcome == "open":
                o.close("unresolved", None)
                o.notes.append(stop)
        self._qualify(work.report)
        work.objections = [asdict(o) for o in self.raised]
        cited = [i for o in self.raised for i in o.evidence + o.citations if i in self.context.records]
        work.report.sources += [i for i in dict.fromkeys(cited) if i not in work.report.sources]

    def _critique(self, work: Work, n: int) -> list[Raised] | None:
        cutoff = self.context.cutoff.isoformat()
        messages = [{"role": "system", "content": prompts.role(CRITIC.name, cutoff, issues=issue_list())},
                    {"role": "user", "content": self._brief(work.report, n)}]
        with self.trace.acting_as(CRITIC.name):
            self.trace.write("critic_start", round=n)
            result = run_loop(self.client, self.model, self.kwargs, messages, self.context, SUBMIT_OBJECTIONS,
                              self.trace, tool_names=CRITIC.tools, max_steps=self.max_steps)
            if result.output is None:
                work.notes.append(f"The critic's review in round {n} ended without objections "
                                  f"({result.error or result.status}), so the report was not reviewed further.")
                self.trace.write("objections", round=n, status=result.status, raised=[], repeats=[])
                return None
            raised, repeats = [], []
            for objection in result.output.objections:
                o, repeat = self._raise(objection, n, work.report)
                raised += [o] if o else []
                repeats += [repeat] if repeat else []
            self.trace.write("objections", round=n, status=result.status, steps=result.steps,
                             raised=[asdict(o) for o in raised], repeats=repeats)
        return raised

    def _raise(self, objection: Objection, n: int, report: CheckedReport) -> tuple[Raised | None, dict | None]:
        current = {c.id: (f"{key}[{i}]", c) for key, claims in report.sections.items() for i, c in enumerate(claims)}
        claim_id = self.ledger.resolve(objection.claim) or objection.claim.strip()
        where, checked = current.get(claim_id, ("not in the report", None))
        version = checked.version if checked else objection.version or 0
        earlier = next((o for o in self.raised if (o.claim, o.version, o.issue) == (claim_id, version, objection.issue)),
                       None)
        if earlier:  # the same issue on the same claim version: no new input, so not raised again
            return None, {"claim": claim_id, "version": version, "issue": objection.issue, "repeat_of": earlier.id}
        problem, used, flags = fill(objection.problem, "problem", self.context.records)
        evidence, unknown = self._resolve(objection.evidence)
        notes = _text_notes(objection.problem, flags, "problem") + [f"Evidence {raw!r} is not an ID any tool returned."
                                                                    for raw in unknown]
        if checked and objection.version not in (None, checked.version):
            notes.append(f"Raised against v{objection.version}; the report has v{checked.version}, so it is about that.")
        o = Raised(make_id("objection", claim_id, version, objection.issue, objection.problem), n, claim_id, version,
                   where, self._owner(claim_id, checked), objection.issue, objection.material, problem,
                   list(dict.fromkeys(used + evidence)), objection.requested_check, notes=notes)
        if not o.evidence:
            o.notes.append("It cites no evidence.")
        if checked is None:
            o.close("unresolved", n)
            o.notes.append("Not routed: it names no claim in the current report.")
        self.raised.append(o)
        return o, None

    def _owner(self, claim_id: str, checked) -> str:
        """The analyst that wrote the claim, else one whose finding the claim cites, else the coordinator."""
        analysts = {role.name for role in ANALYSTS}
        authors = [v["author"] for v in self.ledger.versions.get(claim_id, [])]
        cited = [v["author"] for i in (checked.citations if checked else []) for v in self.ledger.versions.get(i, [])]
        return next((a for a in authors + cited if a in analysts), COORDINATOR.name)

    def _revise(self, work: Work, n: int, pending: list[Raised]) -> bool:
        asked, before = len(self.desk.asked), {c.id for claims in work.report.sections.values() for c in claims}
        self.trace.write("revision_start", round=n, objections=[o.id for o in pending])
        work.messages.append({"role": "user", "content": self._request(work, n, pending)})
        result = work.resume(SUBMIT_REVISION, max_steps=self.max_steps)  # each revision gets its own step guard
        if result.output is None:
            work.notes.append(f"The revision in round {n} ended without a report ({result.error or result.status}); "
                              "the report before it is shown.")
            return False
        work.draft, work.status = result.output, result.status
        work.report = check_draft(work.draft, self.context, self.trace, self.ledger, COORDINATOR.name)
        self._settle(work.report, n, pending, result.output, set(self.desk.asked[asked:]), before)
        return True

    def _settle(self, report: CheckedReport, n: int, pending: list[Raised], revision: Revision, asked: set[str],
                before: set[str]):
        """Each objection's outcome, from the ledger (did the claim change or go?) and the coordinator's answer."""
        current = {c.id: c for claims in report.sections.values() for c in claims}
        added, risks = [i for i in current if i not in before], {c.id for c in report.sections.get("risks", [])}
        given = {}
        for i, out in enumerate(revision.outcomes):
            key = "objection-" + out.objection.strip().strip("{}").removeprefix("objection:").removeprefix("objection-")
            given[key] = (i, out)
        for o in pending:
            i, out = given.get(o.id, (None, None))
            explanation, citations = None, []
            if out:
                explanation, used, flags = fill(out.explanation, f"outcomes[{i}]", self.context.records)
                resolved, unknown = self._resolve(out.citations)
                citations = list(dict.fromkeys(used + resolved))
                o.notes += _text_notes(out.explanation, flags, f"round {n} explanation") + [f"Round {n}: citation {raw!r} is not an ID any tool "
                                                               "returned." for raw in unknown]
            evidence = self._evidence(citations)
            if claims := [c for c in citations if c not in evidence]:
                o.notes.append(f"Round {n}: citing claims ({', '.join(claims)}) is not evidence; only tool records count.")
            if o.owner != COORDINATOR.name and o.owner not in asked:
                o.notes.append(f"Round {n}: the coordinator answered it without asking the {o.owner} analyst.")
            claim = current.get(o.claim)
            if claim is None:
                o.close("withdrawn", n, explanation, citations)
                self.ledger.withdraw(o.claim, o.version, o.id)
                if out and out.outcome != "withdrawn":
                    o.notes.append(f"Called {out.outcome}, but the claim is no longer in the report, so it is recorded "
                                   "as withdrawn.")
            elif out and out.outcome in ("defended", "unresolved"):
                if out.outcome == "defended" and not evidence:
                    o.notes.append(f"Round {n}: defended without citing evidence, so it stays open.")
                    continue
                o.close(out.outcome, n, explanation, citations)
                if claim.version != o.version:
                    o.notes.append(f"The claim has since changed to v{claim.version}; this outcome is about "
                                   f"v{o.version}.")
            elif o.issue == "missing_material_risk" and out and out.outcome == "corrected" and added:
                # A missing risk is fixed by adding a claim, so the claim it qualifies may stay as it was. Whether the
                # added claim is about this risk isn't checked: that would need another model call.
                cited = [i for i in added if i in risks and self._evidence(current[i].citations)]
                if not (evidence and cited):
                    o.notes.append(f"Round {n}: a claim was added, but it stays open: that needs a new Risks claim and "
                                   "an outcome that each cite a tool record.")
                    continue
                o.close("corrected", n, explanation, citations)
                o.new_claims = cited
            elif claim.version != o.version and out and out.outcome == "corrected" and evidence:
                o.close("corrected", n, explanation, citations, new_version=claim.version)
            elif claim.version != o.version:
                why = "no outcome was given" if out is None else (
                    "corrected without evidence" if out.outcome == "corrected" else f"called {out.outcome}")
                o.notes.append(f"Round {n}: the claim changed to v{claim.version}, but no evidence it fixes the problem "
                               f"({why}), so it stays open.")
            else:
                o.notes.append(f"Round {n}: " + (f"called {out.outcome}, but the claim is unchanged at v{o.version}"
                                                 if out else "no outcome was given") + ", so it stays open.")
        unknown = [out.objection for key, (_, out) in given.items() if key not in {o.id for o in pending}]
        self.trace.write("outcomes", round=n, unknown_objections=unknown, outcomes=[
            {"objection": o.id, "claim": o.claim, "version": o.version, "outcome": o.outcome,
             "new_version": o.new_version, "new_claims": o.new_claims, "notes": o.notes} for o in pending])

    def _evidence(self, ids: list[str]) -> list[str]:
        """The tool records among `ids`. A claim (a report statement or an analyst's finding) can't close an objection."""
        return [i for i in ids if (record := self.context.records.get(i)) and record.get("kind") != "claim"]

    def _resolve(self, raw_ids: list[str]) -> tuple[list[str], list[str]]:
        resolved, unknown = [], []
        for raw in raw_ids:
            match = CITATION.fullmatch(raw.strip())
            found = lookup(self.context.records, *((match[2], match[1]) if match else (raw.strip(),)))
            # Live check 3 Nov 2026: the critic cited a report claim, which is a claim, not a tool record.
            claim = None if found else self.ledger.resolve(raw) if "claim" in raw else None
            if found or claim:
                resolved.append(found["id"] if found else claim)
            else:
                unknown.append(raw)
        return resolved, unknown

    def _qualify(self, report: CheckedReport):
        """A claim with a material objection left unresolved, or that cites a withdrawn claim, is qualified. So is a
        claim that cites one with such an objection: one step only, not the whole chain. An open objection follows
        its claim to newer versions, since only evidence closes it."""
        open_ = {o.claim: o for o in self.raised if o.outcome == "unresolved" and o.material}
        for key, claims in report.sections.items():
            for i, c in enumerate(claims):
                problems = [f"Objection {o.id} ({o.issue.replace('_', ' ')}) is unresolved: {o.problem}"
                            for o in self.raised if (o.claim, o.outcome) == (c.id, "unresolved") and o.material]
                problems += [f"It cites {cited}, which was withdrawn after "
                             f"{self.ledger.withdrawn[cited]['objection']}." for cited in c.citations
                             if cited in self.ledger.withdrawn]
                problems += [f"It cites {cited}, which has unresolved objection {o.id} ({o.issue.replace('_', ' ')})."
                             for cited in c.citations if cited != c.id and (o := open_.get(cited))]
                for problem in problems:
                    c.flags.append(Flag(f"{key}[{i}]", problem))
                    report.flags.append(c.flags[-1])

    def _brief(self, report: CheckedReport, n: int) -> str:
        history = "\n".join(self._line(o) for o in self.raised) or "None: this is the first review."
        limits = "\n".join(f"- {text}" for text in report.limitations) or "(none)"
        return (f"The user's question: {self.question}\n\nReview {n} of at most {self.rounds}. The report's claims "
                "(ID, version, where, kind, materiality), as they read with the numbers filled in, with the records "
                f"each cites and any checker flags:\n{claims_view(report)}\n\nThe evidence they cite:\n"
                f"{evidence_view(report.sources, self.context.records)}\n\nLimitations the report states:\n{limits}\n\n"
                f"Objections so far and how they ended:\n{history}\n\nReview the report and call submit_objections.")

    @staticmethod
    def _line(o: Raised) -> str:
        line = (f"- {o.id} on {o.claim} v{o.version} ({o.issue}, {'material' if o.material else 'minor'}): "
                f"{o.problem} Requested check: {o.requested_check} Outcome: {o.outcome}")
        line += (f" (now v{o.new_version})" if o.new_version else "") + (f": {o.explanation}" if o.explanation else "")
        return line + (f" Cites {', '.join(o.citations)}." if o.citations else "") + "".join(
            f"\n  Note: {note}" for note in o.notes)

    def _request(self, work: Work, n: int, pending: list[Raised]) -> str:
        lines = []
        for o in pending:
            who = "you (no analyst finding behind it)" if o.owner == COORDINATOR.name else f"ask_{o.owner}"
            lines.append(f"- {o.id} on {o.claim} v{o.version} ({o.where}; owner: {who}): {o.issue}, "
                         f"{'material' if o.material else 'minor'}. {o.problem} Evidence: "
                         f"{', '.join(o.evidence) or 'none cited'}. Requested check: {o.requested_check}"
                         + (f"\n  Note: {o.notes[-1]}" if o.notes else ""))
        return (f"The critic reviewed your report (round {n}) and raised these objections:\n" + "\n".join(lines) +
                "\n\nFor each objection:\n1. Ask the analyst that owns the claim (its ask_ tool) to run the requested "
                "check: give the objection ID, the claim and what is in doubt. It continues its earlier work. If you "
                "own the claim, ask the analyst whose evidence it rests on, or check it yourself with calculate.\n"
                "2. Decide the outcome from what the check finds, not from agreeing with the critic:\n"
                "- defended: the evidence answers the objection; cite the record or check that shows it.\n"
                "- corrected: revise the claim so it rests on the right evidence, keep its claim ID in `id`, fix what "
                "depends on it, and cite the records that show the fix.\n- withdrawn: remove the claim when the "
                "evidence doesn't support it, and reconsider what depended on it.\n- unresolved: no tool can settle it; say what it affects.\n"
                "3. Call submit_revision with the complete report (every section; every statement you keep has its "
                "claim ID in `id`, and an unchanged statement stays exactly as it is) and one outcome per objection."
                "\n\nYour current report, with each statement's claim ID:\n"
                + json.dumps(draft_with_ids(work.draft, work.report), ensure_ascii=False, indent=1))


def _text_notes(text: str, flags: list[Flag], what: str) -> list[str]:
    """One note for the figures a critic or coordinator typed (flagged, never removed), plus any other flag."""
    typed = list(dict.fromkeys(typed_numbers(text)))
    other = [flag.problem for flag in flags if "is typed, not a" not in flag.problem]
    return [f"The {what} types {', '.join(map(repr, typed))} instead of placeholders, so no tool result backs "
            f"{'it' if len(typed) == 1 else 'them'}."] * bool(typed) + other
