"""Agent runs from the web page (PROJECT_GUIDE Phase 7, the thin web path): start a run of condition B, C or D in the
background, follow its progress, cancel it and read its checked report. Saved runs are the trace files in
data/traces/ (agents/saved.py), so History also lists runs started from the CLI."""
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated, Literal

from fastapi import APIRouter, Request
from pydantic import BaseModel, StringConstraints

from . import cli
from .agents import saved
from .agents.trace import Trace
from .contracts import DomainError
from .model_access import load_model_settings
from .tools.result import ToolContext

router = APIRouter(prefix="/api/agent-runs")


class StartRun(BaseModel):
    question: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
    condition: Literal["B", "C", "D"] = "D"  # the analyst team with its critic: the full design


class AgentRuns:
    """The runs this server started, each on its own thread, with the flag that cancels it."""

    def __init__(self, folder: Path):
        self.folder = folder
        self.active: dict[str, threading.Event] = {}
        self.lock = threading.Lock()

    def start(self, question: str, condition: str, settings) -> str:
        trace, stop = Trace.new(self.folder), threading.Event()
        with self.lock:
            self.active[trace.run_id] = stop
        threading.Thread(target=self._run, args=(question, condition, settings, trace, stop), daemon=True).start()
        return trace.run_id

    def _run(self, question: str, condition: str, settings, trace: Trace, stop: threading.Event):
        try:
            with cli.sec_client() as sec, cli.model_client(settings) as client:
                context = ToolContext(cutoff=datetime.now(timezone.utc), sec=sec, stop=stop)
                cli.CONDITIONS[condition](question, client, settings, context, trace=trace)
        except Exception as exc:  # a bug must still end the trace, or the page would show the run going forever
            if not trace.seq:
                trace.write("run_start", question=question, condition=cli.LABELS[condition])
            trace.write("run_end", status="failed", error=f"{type(exc).__name__}: {exc}", totals=dict(trace.totals))
        finally:
            with self.lock:
                del self.active[trace.run_id]

    def cancel(self, run_id: str) -> bool:
        with self.lock:
            stop = self.active.get(run_id)
        if stop:
            stop.set()
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
        found = saved.summary(path) if saved.RUN_ID.fullmatch(run_id) and path.is_file() else None
        if found is None and run_id not in active:
            raise DomainError("No saved agent run has that ID.", "not_found", 404)
        return _status(found or {"run_id": run_id, "status": None}, active)  # a run so new it has no event yet

    def history(self) -> list[dict]:
        active = self._active()
        return [_status(found, active) for found in saved.runs(self.folder)]

    def _active(self) -> dict[str, threading.Event]:
        # Read before the trace: a run writes run_end before it leaves `active`, so it never looks incomplete.
        with self.lock:
            return dict(self.active)


def _status(found: dict, active: dict[str, threading.Event]) -> dict:
    if found["status"] is None:
        stop = active.get(found["run_id"])
        # incomplete: no run_end and not running here (a CLI run still going, or a server stopped mid-run)
        found["status"] = "incomplete" if stop is None else "stopping" if stop.is_set() else "running"
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
    return runs(request).view(runs(request).start(body.question, body.condition, settings))


@router.get("")
def history(request: Request):
    return {"items": runs(request).history()}


@router.get("/{run_id}")
def progress(run_id: str, request: Request):
    view, path = runs(request).view(run_id), runs(request).path(run_id)
    return {**view, "progress": saved.progress(path) if path.is_file() else []}


@router.post("/{run_id}/cancel")
def cancel(run_id: str, request: Request):
    if not runs(request).cancel(run_id):
        raise DomainError("This run is not running here, so there is nothing to cancel.", "not_running", 409)
    return runs(request).view(run_id)


@router.get("/{run_id}/report")
def report(run_id: str, request: Request):
    view = runs(request).view(run_id)
    if view["status"] in ("running", "stopping", "incomplete"):
        raise DomainError("This run has no report yet: it is still running, or it stopped without writing one.",
                          "no_report", 409)
    return {**view, **saved.report(runs(request).path(run_id))}
