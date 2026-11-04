"""Discover's first step (REFERENCE §4 rules 1-2): the question becomes a screen spec, shown before anything runs.

Every vague term ("cheap", "large", "fast-growing") comes back with a stated definition and a question. The user
answers it (their answer goes back to the model, which revises the spec), accepts the proposal, or isn't asked, and
then the definition stands labelled "assumed". Nothing is defined silently.
"""
import re
from dataclasses import dataclass, field
from typing import Callable, Literal

from pydantic import BaseModel, Field

from .. import config
from ..data.universe import Universe
from ..model_access import ModelSettings
from ..tools.result import ToolContext
from ..tools.screen import Filter, Metric
from . import prompts
from .loop import Finish, run_loop
from .trace import Trace

# Need prices, so they are checked per candidate after the screen (REFERENCE §4 rule 9).
PRICE_METRICS = ("market_cap", "pe", "ps", "pb", "fcf_yield", "volatility", "max_drawdown")


class PriceCheck(BaseModel):
    metric: Literal[PRICE_METRICS]
    op: Literal[">", ">=", "<", "<="]
    value: float = Field(description="Multiples as numbers (30 for 30x), yields and drawdowns as fractions, "
                                     "market cap in US dollars.")


class Term(BaseModel):
    term: str = Field(min_length=1, description="The vague words as the user wrote them.")
    definition: str = Field(min_length=1, description="The filter, price check or ranking it became, with its threshold.")
    question: str = Field(min_length=1, description="One short question that lets the user set it.")


class ScreenSpec(BaseModel):
    filters: list[Filter] = Field(default_factory=list)
    sic_prefixes: list[str] | None = Field(None, description='SIC industry code prefixes to keep, e.g. ["357", "7372"].')
    rank_by: Metric
    descending: bool = True
    top_k: int | None = Field(None, ge=1, description="How many companies the user wants; empty if they didn't say.")
    price_checks: list[PriceCheck] = Field(default_factory=list)
    terms: list[Term] = Field(default_factory=list, description="Every vague term, with its definition and question.")
    not_covered: list[str] = Field(default_factory=list, description="What the screen and checks can't express.")


SUBMIT_SPEC = Finish("submit_screen_spec", "Hand in the screen spec: filters, ranking, price checks, how many "
                     "companies, every vague term with its definition and question, and what isn't covered.",
                     ScreenSpec)

# How each term's definition was settled, as the shortlist shows it.
SOURCES = {"user": "set by the user", "accepted": "proposed and accepted by the user",
           "assumed": "assumed: not confirmed by the user", "proposed": "proposed: waiting for the user's answer"}


@dataclass
class Interpretation:
    spec: ScreenSpec | None
    sources: dict[str, str] = field(default_factory=dict)  # term -> user | accepted | assumed
    status: str = "finished"
    error: str | None = None


def interpret(question: str, universe: Universe, client, settings: ModelSettings, context: ToolContext,
              trace: Trace, *, ask: Callable[[Term], str | None] | None = None,
              defined: dict[str, str] | None = None,
              on_questions: Callable[[ScreenSpec, list[Term]], None] | None = None,
              edit: Callable[[ScreenSpec], ScreenSpec | None] | None = None, review: bool = False) -> Interpretation:
    """`ask` returns the user's answer to a term's question: text to set it, "" to accept the proposal, None when
    nobody can be asked. `defined` holds terms the user defined up front (term -> meaning). `on_questions` gets
    the draft spec and the terms about to be asked, so the user sees the whole spec before answering. `edit`
    returns the spec as the user edited it directly (the page's spec editor), or None to keep the draft; an edited
    spec is used as it is, with no model call. `review` shows the spec for checking even when no term is asked."""
    defined = defined or {}
    kwargs = settings.request_kwargs(fallbacks=True)  # no output-token cap (PROJECT_GUIDE §5)
    given = "".join(f"\n- {term}: {meaning}" for term, meaning in defined.items())
    messages = [{"role": "system", "content": prompts.load(
                    "screener", cutoff=context.cutoff.isoformat(), universe=describe(universe),
                    default_top_k=config.DISCOVER_DEFAULT_TOP_K)},
                {"role": "user", "content": question + (f"\n\nThe user defined these terms:{given}" if given else "")}]
    result = run_loop(client, settings.model, kwargs, messages, context, SUBMIT_SPEC, trace, tool_names=())
    if result.output is None:
        return Interpretation(None, status=result.status, error=result.error or "No screen spec was handed in.")
    spec, sources, answers = result.output, {}, {}
    asked = [term for term in spec.terms if not _match(term.term, defined)]
    if on_questions and ((ask and asked) or review):
        on_questions(spec, asked)
    for term in spec.terms:
        if _match(term.term, defined):
            sources[term.term] = "user"
            continue
        answer = ask(term) if ask else None
        trace.write("clarify", term=term.term, question=term.question, proposal=term.definition, answer=answer)
        if answer is None:
            sources[term.term] = "assumed"
        elif not answer.strip():
            sources[term.term] = "accepted"
        else:
            answers[term.term] = answer.strip()
    edited = edit(spec) if edit else None
    if edited is not None:
        trace.write("spec_edit", spec=edited.model_dump(mode="json"))
        draft = {t.term: t.definition for t in spec.terms}
        # A term the user left as drafted was seen and accepted; a changed or new one is theirs.
        sources = {t.term: "user" if draft.get(t.term) != t.definition or sources.get(t.term) == "user"
                   else "accepted" for t in edited.terms}
        return Interpretation(edited, sources, result.status)
    if answers:
        messages.append({"role": "user", "content": "The user answered your questions:" + "".join(
            f"\n- {term}: {answer}" for term, answer in answers.items()) + "\n\nRevise the spec so it uses these "
            "definitions, keep each term's wording, and call submit_screen_spec again with the whole spec."})
        again = run_loop(client, settings.model, kwargs, messages, context, SUBMIT_SPEC, trace, tool_names=(),
                         max_steps=max(config.AGENT_MAX_STEPS - result.steps, 1))
        if again.output is None:
            return Interpretation(None, status=again.status, error=again.error or "The revised spec wasn't handed in.")
        spec = again.output
        earlier = sources | dict.fromkeys(answers, "user") | dict.fromkeys(defined, "user")
        sources = {t.term: next((s for key, s in earlier.items() if _match(t.term, {key: s})), "assumed")
                   for t in spec.terms}
    return Interpretation(spec, sources, result.status)


def describe(universe: Universe) -> str:
    members = "\n".join(f"- {m.ticker}: {m.name}" + (f" ({m.sector})" if m.sector else "") for m in universe.members)
    return (f"{universe.name}: {len(universe.members)} tickers, {len(universe.ciks)} companies (share classes count "
            f"once). Source: {universe.source}, as of {universe.as_of}. {universe.note}\n\n{members}")


def _key(text: str) -> str:
    return " ".join(re.findall(r"[a-z0-9%$.]+", text.casefold()))


def _match(term: str, terms: dict[str, str]) -> str | None:
    """The entry whose wording contains the term's, or the other way round ("valuation" and "a reasonable valuation")."""
    key = _key(term)
    return next((value for name, value in terms.items() if key and _key(name) and
                 (_key(name) in key or key in _key(name))), None)
