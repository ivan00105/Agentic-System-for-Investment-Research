"""Serve the web app, answer one research question in the terminal with the single agent (condition B), the
analyst team (condition C) or the team with its critic (condition D), review a saved run's draft with the critic,
or recheck a saved run's numbers offline from its trace."""
import argparse
import sys
from datetime import date, datetime, time, timezone
from pathlib import Path

import uvicorn
from dotenv import load_dotenv
from openai import OpenAI

from . import config
from .agents import critic, evidence, isolated_review, single_agent, team
from .data.sec import SecClient
from .model_access import load_model_settings
from .tools.result import ToolContext

# Factories, so tests can swap in fixtures and a scripted model.
sec_client = SecClient
# Evaluation conditions the CLI can run (REFERENCE §7); A is the web app's fixed pipeline.
CONDITIONS = {"B": single_agent.run, "C": team.run, "D": critic.run}


def model_client(settings):
    return OpenAI(**settings.client_kwargs, max_retries=config.AGENT_MODEL_RETRIES)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Serve the local research workspace, or answer one question.")
    parser.add_argument("question", nargs="?", help="A research question. Without one, the web app is served.")
    parser.add_argument("--cutoff", type=date.fromisoformat, metavar="YYYY-MM-DD",
                        help="Research as of the end of this day (UTC). Default: now.")
    parser.add_argument("--condition", choices=sorted(CONDITIONS), default="B",
                        help="B: one agent with every tool (default). C: a coordinator with fundamentals, "
                             "filings and market analysts. D: C plus a critic whose objections the team answers.")
    parser.add_argument("--recheck", type=Path, metavar="TRACE",
                        help="Recheck a saved run's numbers from its trace file, offline (no network, no model).")
    parser.add_argument("--review", type=Path, metavar="TRACE",
                        help="Run condition D's critic and revisions on a saved run's final draft and frozen evidence.")
    parser.add_argument("--inject", choices=sorted(isolated_review.DEFECTS),
                        help="With --review: first plant a labelled test defect in the saved draft.")
    args = parser.parse_args(argv)
    if args.inject and not args.review:
        parser.error("--inject needs --review TRACE")
    if args.recheck:
        return recheck(args.recheck)
    if args.review:
        return review(args.review, args.inject)
    if args.question is None:
        uvicorn.run("research_assistant.api:create_app", factory=True, host="127.0.0.1", port=8000, workers=1)
        return 0
    return ask(args.question, args.cutoff, args.condition)


def utf8_console():
    for stream in (sys.stdout, sys.stderr):  # Windows consoles default to a legacy code page
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")


def model_settings():
    """The model settings from .env, or None after saying what to set."""
    utf8_console()
    load_dotenv(config.PROJECT_ROOT / ".env", override=False, interpolate=False, encoding="utf-8-sig")
    settings = load_model_settings()
    if not settings.configured:
        print(settings.error or "Model access is not configured: set RESEARCH_MODEL_PROVIDER, RESEARCH_MODEL and "
              "the provider's API key in .env (see .env.example).", file=sys.stderr)
        return None
    return settings


def ask(question: str, cutoff_day: date | None, condition: str = "B") -> int:
    if (settings := model_settings()) is None:
        return 2
    cutoff = datetime.combine(cutoff_day, time.max, timezone.utc) if cutoff_day else datetime.now(timezone.utc)
    with sec_client() as sec, model_client(settings) as client:
        if not sec.configured:
            print("SEC_USER_AGENT is not set: SEC tools answer 'unavailable' except for cached data.", file=sys.stderr)
        result = CONDITIONS[condition](question, client, settings, ToolContext(cutoff=cutoff, sec=sec), echo=progress)
    return show(result)


def review(path: Path, inject: str | None) -> int:
    if (settings := model_settings()) is None:
        return 2
    with sec_client() as sec, model_client(settings) as client:
        try:
            result = isolated_review.run(path, client, settings, sec, inject=inject, echo=progress)
        except (OSError, isolated_review.NotReviewable) as exc:
            print(exc, file=sys.stderr)
            return 2
    return show(result)


def show(result) -> int:
    print(result.markdown)
    print(f"Trace saved to {result.trace_path}")
    return 1 if result.status == "failed" else 0


def recheck(path: Path) -> int:
    utf8_console()
    result = evidence.recheck(path)
    print(f"Rechecked {result.calcs} calculations and {result.statements} report statements offline from {path}.")
    print("\n".join(f"- {problem}" for problem in result.problems) or "Every number matches the saved run.")
    return 1 if result.problems else 0


def progress(event: dict):
    """One line per step on stderr, so a run of a few minutes isn't silent."""
    kind, step = event["kind"], event.get("step")
    if kind == "plan":
        line = "plan ready"
    elif kind == "model_call":
        calls = [c["function"]["name"] for c in event["tool_calls"]]
        line = f"step {step}: model asks for {', '.join(calls) or 'no tool'}"
    elif kind == "tool_call":
        line = f"step {step}: {event['name']} -> {event['result']['status']}" + (" (repeat)" if event["repeat_of"] else "")
    elif kind == "check":
        line = f"checker: {len(event['flags'])} flags"
    elif kind == "analyst_start":
        line = ("follow-up: " if event["follow_up"] else "task: ") + " ".join(event["task"].split())
    elif kind == "analyst_end":
        line = f"done ({event['status']}): {event['findings']} findings"
    elif kind == "critic_start":
        line = f"review round {event['round']}"
    elif kind == "objections":
        material = sum(1 for o in event["raised"] if o["material"])
        line = (f"round {event['round']}: {len(event['raised'])} objections ({material} material), "
                f"{len(event['repeats'])} repeats")
    elif kind == "revision_start":
        line = f"revising for {len(event['objections'])} objections"
    elif kind == "outcomes":
        line = "outcomes: " + ", ".join(f"{o['objection']} {o['outcome']}" for o in event["outcomes"])
    elif kind == "injected":
        line = f"injected {event['defect']}: {event['change']}"
    elif kind in ("self_review", "stopped_at_limit", "nudge", "error"):
        line = f"{kind.replace('_', ' ')}" + (f": {event['error']}" if kind == "error" else "")
    else:
        return
    who = f"[{event['agent']}] " if event.get("agent") else ""  # the role that did it (condition C)
    print(who + line, file=sys.stderr, flush=True)


if __name__ == "__main__":
    sys.exit(main())
