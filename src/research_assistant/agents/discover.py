"""Discover mode (PROJECT_GUIDE §1, REFERENCE §4): the question becomes a screen spec shown to the user (vague terms
asked about or stated), `screen` ranks a declared universe, and each ranked candidate in turn gets the acceptance
test on its latest 10-K and price, then a research run by condition B, C or D. A candidate that fails the test, or
whose research fails (including a run that ends with no claims in any section), is replaced by the next one. The
result is a shortlist with counts; fewer than k is fine and says why.

The Discover trace holds the spec step, the host's tool calls and one event per candidate; each research run keeps
its own trace, and the Discover run's totals add theirs in.
"""
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable

from .. import config
from ..data.universe import Universe
from ..model_access import ModelSettings, decoding_record
from ..tools.result import ToolContext
from .acceptance import Acceptance, Verdict, threshold
from .discover_report import render, spec_lines
from .discover_spec import Interpretation, ScreenSpec, Term, interpret
from .runner import AgentRun
from .trace import Trace, _zero

Research = Callable[..., AgentRun]  # single_agent.run, team.run or critic.run


@dataclass
class Candidate:
    rank: int
    cik: str
    name: str | None
    tickers: list[str]
    values: dict[str, str | None]  # the screen's values, from SEC frames
    verdict: Verdict | None = None
    run: AgentRun | None = None
    error: str | None = None  # the research run raised instead of returning
    outcome: str = "not reached"  # picked | rejected | research failed | not reached


@dataclass
class DiscoverRun:
    run_id: str
    status: str  # finished | failed
    interpretation: Interpretation
    counts: dict
    candidates: list[Candidate]
    markdown: str
    trace_path: Path
    totals: dict
    error: str | None = None
    notes: list[str] = field(default_factory=list)


def run(question: str, client, settings: ModelSettings, context: ToolContext, universe: Universe, *,
        research: Research, condition: str, ask: Callable[[Term], str | None] | None = None,
        defined: dict[str, str] | None = None, replacements: int = config.DISCOVER_MAX_REPLACEMENTS,
        trace_dir: Path | None = None, echo: Callable[[dict], None] | None = None,
        trace: Trace | None = None, edit: Callable[[ScreenSpec], ScreenSpec | None] | None = None,
        review: bool = False, top_k: int | None = None) -> DiscoverRun:
    """`trace` is one the host made already, so it knows the run ID before the run starts (the web app). `edit`
    lets the user edit the drafted spec directly before the screen, and `review` shows it even with no vague term
    (discover_spec.interpret). `top_k` is a count the user set apart from the question; it replaces the spec's."""
    trace = trace or Trace.new(trace_dir, echo)
    trace.write("run_start", question=question, cutoff=context.cutoff.isoformat(), condition=f"Discover ({condition})",
                lead="screener", provider=settings.provider, model=settings.model, decoding=decoding_record(),
                universe=universe.name, replacements=replacements)
    with trace.acting_as("screener"):
        found = interpret(question, universe, client, settings, context, trace, ask=ask, defined=defined,
                          edit=edit, review=review, top_k=top_k, on_questions=lambda draft, terms: trace.write(  # shown before the user is asked
                              "questions", terms=[t.model_dump() for t in terms], shown=spec_lines(
                                  draft, dict.fromkeys((t.term for t in terms), "proposed"), universe,
                                  draft.top_k or config.DISCOVER_DEFAULT_TOP_K, condition),
                              spec=draft.model_dump(mode="json")))
    if found.spec is None or context.stop.is_set():  # cancelled, perhaps while the user was asked: nothing is screened
        return _close(trace, question, settings, context, universe, found, condition, [], {}, [],
                      None if context.stop.is_set() else found.error)
    spec = found.spec
    top_k = spec.top_k or config.DISCOVER_DEFAULT_TOP_K
    trace.write("screen_spec", spec=spec.model_dump(mode="json"), top_k=top_k, terms=found.sources,
                shown=spec_lines(spec, found.sources, universe, top_k, condition))
    host = Acceptance(context, trace)
    with trace.acting_as("host"):
        # Every ranked candidate, not only the top k, so replacements come from the same ranking.
        screened = host.call("screen", {"universe": universe.ciks, "sic_prefixes": spec.sic_prefixes,
                                        "filters": [f.model_dump() for f in spec.filters], "rank_by": spec.rank_by,
                                        "descending": spec.descending, "top_k": len(universe.ciks)})
    if screened.status != "ok":
        return _close(trace, question, settings, context, universe, found, condition, [], {}, [],
                      f"The screen came back {screened.status}: {' '.join(screened.warnings)}", top_k=top_k)
    ranked = [Candidate(c["rank"], c["cik"], c["name"], c["tickers"], c["values"]) for c in screened.data["candidates"]]
    budget, notes, researched = top_k + replacements, list(screened.warnings), 0
    for candidate in ranked:
        if sum(c.outcome == "picked" for c in ranked) == top_k:
            break
        if context.stop.is_set():
            notes.append("Cancelled: the candidates after this point were not checked or researched.")
            break
        if researched == budget:
            notes.append(f"Stopped at the research limit: {budget} research runs (top {top_k} plus {replacements} "
                         "replacements). Raise --replacements to research more candidates.")
            break
        with trace.acting_as("host"):
            candidate.verdict = host.check(candidate.cik, candidate.tickers, [*spec.filters, *spec.price_checks])
        trace.write("candidate", rank=candidate.rank, cik=candidate.cik, name=candidate.name,
                    verdict=candidate.verdict.state, lines=[asdict(line) for line in candidate.verdict.lines])
        if candidate.verdict.state != "pass":
            candidate.outcome = "rejected"
            continue
        researched += 1
        brief = _brief(question, candidate, spec, universe, sum(c.outcome == "picked" for c in ranked) + 1, top_k)
        child = Trace.new(trace.path.parent, echo, parent_run_id=trace.run_id)
        trace.write("research_start", rank=candidate.rank, cik=candidate.cik, name=candidate.name, question=brief,
                    run_id=child.run_id)
        try:
            candidate.run = research(brief, client, settings, ToolContext(
                cutoff=context.cutoff, sec=context.sec, price_providers=context.price_providers,
                cache_dir=context.cache_dir, stop=context.stop), trace=child)
        except Exception as exc:  # a bug in one research run must not lose the others; its own trace shows where
            candidate.error = f"The research run crashed ({type(exc).__name__}: {exc}). This is a bug."
        run = candidate.run
        if run is not None and run.status != "failed" and not any(run.report.sections.values()):
            candidate.error = ("The research run stopped at its step limit with no claims."
                               if run.status == "stopped_at_limit" else "The research run abstained in every section.")
        candidate.outcome = "research failed" if run is None or run.status == "failed" or candidate.error else "picked"
        trace.write("research_end", rank=candidate.rank, cik=candidate.cik, run_id=run and run.run_id,
                    trace=run and str(run.trace_path), status=run.status if run else "crashed",
                    error=candidate.error or (run.error if run else None), totals=run.totals if run else None)
    counts = _counts(screened.data["counts"], ranked, top_k)
    if counts["returned"] < top_k and not any(n.startswith("Stopped at the research limit") for n in notes):
        notes.append(f"Every ranked candidate was checked: {counts['returned']} of the {top_k} asked for passed.")
    return _close(trace, question, settings, context, universe, found, condition, ranked, counts, notes, None,
                  top_k=top_k)


def _brief(question: str, candidate: Candidate, spec, universe: Universe, pick: int, top_k: int) -> str:
    """The research question for one candidate: the user's request, why it was shortlisted, and its scope."""
    criteria = [threshold(c.metric, c.op, c.value) for c in [*spec.filters, *spec.price_checks]]
    if spec.sic_prefixes:
        criteria.append(f"SIC industry code starting with {' or '.join(spec.sic_prefixes)}")
    terms = "".join(f"\n- {t.term}: {t.definition}" for t in spec.terms)
    who = f"{candidate.name} ({', '.join(candidate.tickers) or 'no ticker'}, CIK {candidate.cik})"
    # Live check 3 Nov 2026: told only its screen rank (5), the agent wrote that the company falls outside the top 3.
    above = (f" The {candidate.rank - pick} ranked above it that aren't picked failed the host's check of these "
             "criteria on their latest 10-K and price, or their research failed." if candidate.rank > pick else "")
    return (f"Explain whether {who} fits this request, and where it doesn't: \"{question}\"\n\nIt is shortlist pick "
            f"{pick} of the {top_k} asked for. A screen of {universe.name} ranked it {candidate.rank} by "
            f"{spec.rank_by.replace('_', ' ')} on these criteria: {'; '.join(criteria) or 'none'}.{above}"
            + (f"\nHow the request's terms were read:{terms}" if terms else "")
            + "\n\nCover its business quality, growth, margins, valuation and main risks, on its latest annual "
            "figures. Research this company only; don't screen for other companies.")


# Reads a _brief back as a short title; tests/test_agent_discover.py keeps the two in step.
BRIEF = re.compile(r"Explain whether (?P<name>[^\n]+) \((?P<tickers>[^()\n]*), CIK \d+\) fits this request"
                   r"(?:[\s\S]*?It is shortlist pick (?P<n>\d+) of the (?P<of>\d+) asked for)?")


def pick_title(question: str | None) -> str | None:
    """A pick's title from its brief, e.g. "Pick 2 of 5: Apple Inc. (AAPL)"; None for any other question.
    Briefs saved before 3 Nov 2026 give no pick number."""
    if not (found := BRIEF.match(question or "")):
        return None
    ticker = found["tickers"].split(", ")[0]
    who = found["name"] + (f" ({ticker})" if ticker != "no ticker" else "")
    return f"Pick {found['n']} of {found['of']}: {who}" if found["n"] else f"Pick: {who}"


def _counts(screen: dict, ranked: list[Candidate], top_k: int) -> dict:
    checked = sum(c.verdict is not None for c in ranked)
    return {"screened": screen["screened"], "eligible": screen["eligible"], "ranked": len(ranked), "checked": checked,
            "rejected": sum(c.outcome == "rejected" for c in ranked),
            "researched": sum(c.outcome in ("picked", "research failed") for c in ranked),
            "failed": sum(c.outcome == "research failed" for c in ranked), "replaced": max(0, checked - top_k),
            "returned": sum(c.outcome == "picked" for c in ranked)}


def _add(into: dict, totals: dict):
    for key, value in totals.items():
        if isinstance(value, (int, float)):
            into[key] = round((into.get(key) or 0) + value, 8)


def _close(trace, question, settings, context, universe, found, condition, ranked, counts, notes, error, *,
           top_k: int | None = None) -> DiscoverRun:
    """Add the research runs' totals to the Discover run's own, render the shortlist and write run_end."""
    totals, by_agent = _zero() | dict(trace.totals), {k: dict(v) for k, v in trace.by_agent.items()}
    for c in ranked:
        if c.run:  # each research run's per-role totals are in its own trace
            _add(totals, c.run.totals)
            _add(by_agent.setdefault("research", _zero()), c.run.totals)
    status = "failed" if error else "stopped" if context.stop.is_set() else "finished"
    model = settings.model + (f" (served by {', '.join(trace.hosts)})" if trace.hosts else "")
    markdown = render(question=question, status=status, cutoff=context.cutoff.isoformat(), model=model,
                      run_id=trace.run_id, error=error, condition=condition, universe=universe, found=found,
                      top_k=top_k, counts=counts, candidates=ranked, records=context.records, notes=notes)
    trace.write("run_end", status=status, error=error, totals=totals, own_totals=dict(trace.totals),
                by_agent=by_agent, counts=counts, terms=found.sources,
                candidates=[{"rank": c.rank, "cik": c.cik, "name": c.name, "outcome": c.outcome,
                             "verdict": c.verdict and c.verdict.state, "run_id": c.run and c.run.run_id,
                             "trace": c.run and str(c.run.trace_path)} for c in ranked if c.outcome != "not reached"],
                notes=notes, markdown=markdown)
    return DiscoverRun(trace.run_id, status, found, counts, ranked, markdown, trace.path, totals, error, notes)
