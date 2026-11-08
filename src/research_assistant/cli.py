"""Serve the web app, answer one research question in the terminal with the single agent (condition B), the
analyst team (condition C) or the team with its critic (condition D), discover companies in a declared universe,
review a saved run's draft with the critic, or recheck a saved run's numbers offline from its trace."""
import argparse
import sys
from datetime import date, datetime, time, timezone
from pathlib import Path

import uvicorn
from dotenv import load_dotenv
from openai import OpenAI

from . import config
from .agents import critic, discover, evidence, isolated_review, single_agent, team
from .agents.progress import describe
from .agents.tool_lines import Seen
from .data import universe
from .data.errors import DataError
from .data.sec import SecClient
from .model_access import load_model_settings
from .tools.result import ToolContext

# Factories, so tests can swap in fixtures and a scripted model.
sec_client = SecClient
# Evaluation conditions the CLI can run (REFERENCE §7); A is the web app's fixed pipeline.
CONDITIONS = {"B": single_agent.run, "C": team.run, "D": critic.run}
LABELS = {"B": single_agent.CONDITION, "C": team.CONDITION, "D": critic.CONDITION}
SEEN = Seen()  # records and company names the progress lines have seen; IDs are content hashes, so runs never clash


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
    parser.add_argument("--universe", metavar="NAME_OR_FILE",
                        help="Discover: screen this declared universe (bundled: " + ", ".join(universe.bundled())
                             + f"; {universe.ALL_FILERS} for every SEC filer with a ticker; or a YAML file), then "
                             "research the top candidates with --condition.")
    parser.add_argument("--define", action="append", default=[], metavar="TERM=MEANING",
                        help="With --universe: define a vague term up front, e.g. 'reasonable valuation=P/E below "
                             "40'. Terms left open are asked about when the terminal is interactive.")
    parser.add_argument("--replacements", type=int, default=config.DISCOVER_MAX_REPLACEMENTS, metavar="N",
                        help="With --universe: research runs allowed beyond top-k to replace failed ones "
                             f"(default {config.DISCOVER_MAX_REPLACEMENTS}).")
    args = parser.parse_args(argv)
    if args.inject and not args.review:
        parser.error("--inject needs --review TRACE")
    if args.universe and args.cutoff:
        parser.error("Discover runs on current data only (SEC frames aren't point-in-time), so --cutoff can't be "
                     "used with --universe")
    if (args.define or args.replacements != config.DISCOVER_MAX_REPLACEMENTS) and not args.universe:
        parser.error("--define and --replacements need --universe")
    if args.replacements < 0:
        parser.error("--replacements can't be negative")
    defined = dict(item.split("=", 1) for item in args.define if "=" in item)
    if len(defined) != len(args.define) or not all(k.strip() and v.strip() for k, v in defined.items()):
        parser.error("--define takes TERM=MEANING, e.g. 'cheap=P/E below 15'")
    if args.recheck:
        return recheck(args.recheck)
    if args.review:
        return review(args.review, args.inject)
    if args.universe:
        if args.question is None:
            parser.error("--universe needs a question")
        return find(args.question, args.universe, args.condition,
                    {k.strip(): v.strip() for k, v in defined.items()}, args.replacements)
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
        context = ToolContext(cutoff=cutoff, sec=sec, historical=cutoff_day is not None)
        result = CONDITIONS[condition](question, client, settings, context, echo=progress)
    return show(result)


def find(question: str, name: str, condition: str, defined: dict[str, str], replacements: int) -> int:
    try:  # a bad name fails before anything else; every SEC filer needs the SEC client first
        declared = None if name == universe.ALL_FILERS else universe.load(name)
    except universe.UniverseError as exc:
        print(exc, file=sys.stderr)
        return 2
    if (settings := model_settings()) is None:
        return 2
    with sec_client() as sec, model_client(settings) as client:
        try:
            declared = declared or universe.load(name, sec)
        except (universe.UniverseError, DataError) as exc:
            print(exc, file=sys.stderr)
            return 2
        if not sec.configured:
            print("SEC_USER_AGENT is not set: SEC tools answer 'unavailable' except for cached data.", file=sys.stderr)
        result = discover.run(question, client, settings, ToolContext(cutoff=datetime.now(timezone.utc), sec=sec),
                              declared, research=CONDITIONS[condition], condition=LABELS[condition], ask=ask_user,
                              defined=defined, replacements=replacements, echo=progress)
    return show(result)


def ask_user(term) -> str | None:
    """A vague term's question on the terminal: an option's number or a definition sets it, Enter accepts the
    proposal. None when no one can be asked (no terminal, or its input is empty), so the proposal stands labelled
    "assumed"."""
    if not sys.stdin.isatty():  # on Windows the NUL device counts as a terminal; input() then hits EOF below
        return None
    options = getattr(term, "options", None) or []
    choices = "".join(f"\n  {n}. {o.definition}" + (" (recommended)" if o.recommended else "")
                      for n, o in enumerate(options, 1))
    print(f"\n{term.question}" + (f"{choices}\n  Type a number or your own definition (Enter accepts the "
                                   "recommended one): " if options else
                                   f"\n  Proposed: {term.definition}\n  Your definition (Enter accepts): "),
          end="", file=sys.stderr, flush=True)
    try:
        while True:
            answer = input()
            if not (options and answer.strip().isdigit()):
                return answer
            if 1 <= int(answer) <= len(options):
                chosen = options[int(answer) - 1]
                return "" if chosen.recommended else chosen.definition
            print(f"  Pick 1 to {len(options)}, or type a definition: ", end="", file=sys.stderr, flush=True)
    except EOFError:
        print("(no answer)", file=sys.stderr)
        return None


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
    """One line per event on stderr, so a run of a few minutes isn't silent."""
    if line := describe(event, SEEN):
        print(line, file=sys.stderr, flush=True)


if __name__ == "__main__":
    sys.exit(main())
