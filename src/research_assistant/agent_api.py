"""Agent runs from the web page (PROJECT_GUIDE Phase 7): start a run of condition B, C or D, or a Discover run over a
declared universe, in the background; follow its progress, answer Discover's questions, cancel it and read its checked
report. Saved runs are the trace files in data/traces/ (agents/saved.py), so History also lists runs started from
the CLI."""
import threading
from dataclasses import replace
from datetime import date, datetime, time, timezone
from pathlib import Path
from typing import Annotated, Literal

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field, StringConstraints, ValidationError, model_validator

from . import cli, config
from .agents import discover, preferences, saved
from .agents.discover_spec import ScreenSpec, unknown_fields
from .agents.trace import Trace
from .contracts import DomainError
from .data import universe as universes
from .data.errors import DataError
from .model_access import load_model_settings
from .tools.result import ToolContext

router = APIRouter(prefix="/api/agent-runs")


class Universe(BaseModel):
    """Discover's universe: a bundled list by name, or the user's own tickers."""
    name: str | None = None
    tickers: list[str] | None = None

    @model_validator(mode="after")
    def _one(self):
        if (self.name is None) == (self.tickers is None):
            raise ValueError("give either a bundled universe name or a list of tickers")
        return self


class StartRun(BaseModel):
    question: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
    # Empty: D, the analyst team with its critic (the full design), or config.WEB_DISCOVER_CONDITION for Discover.
    condition: Literal["B", "C", "D"] | None = None
    cutoff: date | None = None  # research as of the end of this day (UTC), as the CLI's --cutoff
    discover: Universe | None = None
    # Another model ID of the configured provider (Advanced options); empty: RESEARCH_MODEL.
    model: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)] | None = None
    # Discover: wait for the user to check or edit the drafted spec, even when it has no vague terms.
    edit_spec: bool = False
    # Discover: how many to return, from the page's count box; sent apart so a hand-edited question can't lose it.
    top_k: int | None = Field(None, ge=1)
    # "Help me start": what matters most, horizon, comfort with price swings, sectors. Added to the question.
    preferences: str | None = None
    # The Discover run whose "Compare these" started this one; History nests it there.
    parent_run_id: Annotated[str, StringConstraints(pattern=saved.RUN_ID.pattern)] | None = None


class Answers(BaseModel):
    answers: dict[str, str]  # term -> the user's definition; "" accepts the proposal
    spec: dict | None = None  # the drafted spec as the user edited it; used as it is


class Pending:
    """A Discover run waiting for the user: answers to its vague-term questions, or an edited spec."""

    def __init__(self):
        self.answers: dict[str, str] = {}
        self.spec: ScreenSpec | None = None
        self.ready = threading.Event()


class AgentRuns:
    """The runs this server started, each on its own thread, with the flag that cancels it."""

    def __init__(self, folder: Path):
        self.folder = folder
        self.active: dict[str, threading.Event] = {}
        self.waiting: dict[str, Pending] = {}
        self.lock = threading.Lock()

    def start(self, question: str, condition: str, settings, cutoff: datetime | None = None,
              universe: universes.Universe | None = None, edit_spec: bool = False, top_k: int | None = None,
              parent_run_id: str | None = None) -> str:
        trace, stop = Trace.new(self.folder, parent_run_id=parent_run_id), threading.Event()
        with self.lock:
            self.active[trace.run_id] = stop
        threading.Thread(target=self._run, args=(question, condition, settings, trace, stop, cutoff, universe,
                                                 edit_spec, top_k), daemon=True).start()
        return trace.run_id

    def _run(self, question: str, condition: str, settings, trace: Trace, stop: threading.Event,
             cutoff: datetime | None, universe: universes.Universe | None, edit_spec: bool, top_k: int | None):
        try:
            with cli.sec_client() as sec, cli.model_client(settings) as client:
                context = ToolContext(cutoff=cutoff or datetime.now(timezone.utc), sec=sec, stop=stop,
                                      historical=cutoff is not None)
                if universe:
                    waiter = Waiter(self, trace.run_id, stop, edit_spec)
                    discover.run(question, client, settings, context, universe, research=cli.CONDITIONS[condition],
                                 condition=cli.LABELS[condition], ask=waiter.ask, trace=trace, edit=waiter.edit,
                                 review=edit_spec, top_k=top_k)
                else:
                    cli.CONDITIONS[condition](question, client, settings, context, trace=trace)
        except Exception as exc:  # a bug must still end the trace, or the page would show the run going forever
            if not trace.seq:
                trace.write("run_start", question=question, condition=cli.LABELS[condition])
            trace.write("run_end", status="failed", error=f"{type(exc).__name__}: {exc}", totals=dict(trace.totals))
        finally:
            with self.lock:
                del self.active[trace.run_id]
                self.waiting.pop(trace.run_id, None)

    def answer(self, run_id: str, answers: dict[str, str], spec: ScreenSpec | None = None) -> bool:
        with self.lock:
            pending = self.waiting.pop(run_id, None)
        if pending:
            pending.answers, pending.spec = answers, spec
            pending.ready.set()
        return pending is not None

    def cancel(self, run_id: str) -> bool:
        with self.lock:  # under the lock, so a waiting run can't register its questions again after this
            stop = self.active.get(run_id)
            if stop:
                stop.set()
                self.waiting.pop(run_id, None)
        return stop is not None

    def stop_all(self):
        with self.lock:
            for stop in self.active.values():
                stop.set()

    def path(self, run_id: str) -> Path:
        return self.folder / f"{run_id}.jsonl"

    def view(self, run_id: str) -> dict:
        """A run's summary. Its status comes from run_end once written, else running, stopping or incomplete."""
        active, path = self._active(), self.path(run_id)
        found = (saved.summary(path, saved.labels(self.folder).get(run_id))
                 if saved.RUN_ID.fullmatch(run_id) and path.is_file() else None)
        if found is None and run_id not in active:
            raise DomainError("No saved agent run has that ID.", "not_found", 404)
        return _status(found or {"run_id": run_id, "status": None}, active)  # a run so new it has no event yet

    def history(self, archived: bool = False) -> list[dict]:
        active = self._active()
        return [_status(found | {"children": [_status(child, active) for child in found["children"]]}, active)
                for found in saved.runs(self.folder, archived)]

    def _active(self) -> dict[str, threading.Event | None]:
        # Read before the trace: a run writes run_end before it leaves `active`, so it never looks incomplete.
        with self.lock:
            return {**self.active, **dict.fromkeys(self.waiting)}  # None marks a run waiting for answers


class Waiter:
    """Discover's `ask` and `edit` for one run: it waits until the page sends one reply (the answers to all its
    questions, perhaps with an edited spec), or until it is cancelled. `review`: wait even when nothing is asked."""

    def __init__(self, runs: AgentRuns, run_id: str, stop: threading.Event, review: bool = False):
        self.runs, self.run_id, self.stop, self.pending, self.review = runs, run_id, stop, Pending(), review

    def _wait(self) -> bool:
        with self.runs.lock:
            if not self.pending.ready.is_set() and not self.stop.is_set():
                self.runs.waiting[self.run_id] = self.pending
        while not self.pending.ready.wait(0.2):
            if self.stop.is_set():  # cancelled: proposals stand as assumed and the run stops before the screen
                with self.runs.lock:
                    self.runs.waiting.pop(self.run_id, None)
                return False
        return True

    def ask(self, term) -> str | None:
        return self.pending.answers.get(term.term) if self._wait() else None  # None if unanswered: assumed

    def edit(self, spec: ScreenSpec) -> ScreenSpec | None:
        """The spec the page sent with its answers, used whenever there is one (live check 5 Nov 2026: an edit sent to
        a run started without review was dropped). Nothing asked and no review: no wait, no edit."""
        if not (self.review or self.pending.ready.is_set()):
            return None
        return self.pending.spec if self._wait() else None


def _status(found: dict, active: dict[str, threading.Event | None]) -> dict:
    if found["status"] is None:
        run_id = found["run_id"]
        # incomplete: no run_end and not running here (a CLI run still going, or a server stopped mid-run)
        found["status"] = ("incomplete" if run_id not in active else "waiting" if active[run_id] is None
                           else "stopping" if active[run_id].is_set() else "running")
    return found


def runs(request: Request) -> AgentRuns:
    return request.app.state.agent_runs


@router.post("", status_code=202)
def start(body: StartRun, request: Request):
    settings = load_model_settings()
    if not settings.configured:  # degrade, never crash: say what to set
        raise DomainError(settings.error or "Model access is not configured: set RESEARCH_MODEL_PROVIDER, "
                          "RESEARCH_MODEL and the provider's API key in .env (see .env.example).",
                          "model_not_configured", 409)
    if body.discover and body.cutoff:  # REFERENCE §4 rule 9
        raise DomainError("Discover runs on current data only, so it takes no cutoff.", "discover_cutoff", 422)
    declared = None
    if body.discover:
        try:
            with cli.sec_client() as sec:
                declared = (universes.load(body.discover.name, sec) if body.discover.name
                            else universes.from_tickers(sec, body.discover.tickers))
        except (universes.UniverseError, DataError) as exc:
            raise DomainError(str(exc), "bad_universe", 422) from exc
    condition = body.condition or (config.WEB_DISCOVER_CONDITION if declared else "D")
    cutoff = datetime.combine(body.cutoff, time.max, timezone.utc) if body.cutoff else None
    settings = replace(settings, model=body.model) if body.model else settings
    question = preferences.attach(body.question, body.preferences)
    return runs(request).view(runs(request).start(question, condition, settings, cutoff, declared,
                                                  body.edit_spec and declared is not None, body.top_k,
                                                  body.parent_run_id))


@router.get("")
def history(request: Request, archived: bool = False):
    return {"items": runs(request).history(archived)}


@router.get("/{run_id}")
def progress(run_id: str, request: Request):
    view, path = runs(request).view(run_id), runs(request).path(run_id)
    questions = saved.questions(path) if view["status"] == "waiting" else None
    return {**view, "progress": saved.progress(path) if path.is_file() else [], "questions": questions}


@router.post("/{run_id}/answers")
def answer(run_id: str, body: Answers, request: Request):
    """Discover's answers to its vague-term questions: text sets a term, "" accepts its proposal. An edited spec
    replaces the draft as it is, so a field it doesn't know is an error, not dropped."""
    if body.spec is not None and (unknown := unknown_fields(body.spec)):
        raise DomainError(f"The edited spec has fields the screen doesn't know, so they would be ignored: "
                          f"{', '.join(unknown)}. Spec fields: {', '.join(ScreenSpec.model_fields)}.", "bad_spec", 422)
    try:
        spec = ScreenSpec.model_validate(body.spec) if body.spec is not None else None
    except ValidationError as exc:
        problems = "; ".join(f"{'.'.join(map(str, e['loc'])) or 'spec'}: {e['msg']}" for e in exc.errors())
        raise DomainError(f"The edited spec isn't valid: {problems}", "bad_spec", 422) from exc
    if not runs(request).answer(run_id, body.answers, spec):
        raise DomainError("This run is not waiting for answers.", "not_waiting", 409)
    return runs(request).view(run_id)


@router.post("/{run_id}/cancel")
def cancel(run_id: str, request: Request):
    if not runs(request).cancel(run_id):
        raise DomainError("This run is not running here, so there is nothing to cancel.", "not_running", 409)
    return runs(request).view(run_id)


@router.get("/{run_id}/records/{record_id}")
def record(run_id: str, record_id: str, request: Request):
    """One cited record for the evidence panel, read from the run's frozen evidence (no data call)."""
    runs(request).view(run_id)
    found = saved.record(runs(request).path(run_id), record_id) if runs(request).path(run_id).is_file() else None
    if found is None:
        raise DomainError("This run holds no record with that ID.", "not_found", 404)
    return found


@router.get("/{run_id}/report")
def report(run_id: str, request: Request):
    view = runs(request).view(run_id)
    if view["status"] in ("running", "stopping", "incomplete"):
        raise DomainError("This run has no report yet: it is still running, or it stopped without writing one.",
                          "no_report", 409)
    return {**view, **saved.report(runs(request).path(run_id))}
