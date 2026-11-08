"""Run evaluation conditions A-D on the cases in eval/cases/, then score them (REFERENCE §7).

    python eval/run_eval.py --conditions B --cases dev-trap-nvda-fiscal-2024-revenue,dev-unknown-ticker-qzxv
    python eval/run_eval.py --conditions A,B,C,D --split dev --out data/eval/dev-grid
    python eval/run_eval.py --rescore data/eval/dev-grid     # offline: no network, no model

Each run's trace goes to <batch>/traces/ and a line to <batch>/runs.jsonl before the run starts, so a crash still
shows up in the scores. The same command again with the same --out skips the runs that ended (failed ones too, so the
failure rate stays honest) and reruns the ones that crashed. A batch's manifest.json records its set-up (model,
prompts, config values, case files, git commit, and any uncommitted changes as a flag and a hash of `git diff`), and a resume with any of them changed is refused, so one batch never
mixes two set-ups. A runs only on the cases the old pipeline supports; B, C and D get every case. On a prompt-injection case the case's text is appended to what the target tool returns, so
every condition reads the same injected filing text, and the trace freezes it.
"""
import argparse
import hashlib
import json
import re
import subprocess
import sys
from contextlib import contextmanager, nullcontext
from dataclasses import replace
from datetime import datetime, time, timezone
from pathlib import Path

from dotenv import load_dotenv

from research_assistant import cli, config
from research_assistant.agents import prompts
from research_assistant.agents.saved import summary
from research_assistant.agents.trace import Trace
from research_assistant.tools import registry
from research_assistant.tools.result import ToolContext

import baseline_a
import score

CONDITIONS = ("A", "B", "C", "D")
ACCESSION = re.compile(r"\d{10}-\d{2}-\d{6}")
ITEM = re.compile(r"\bItem\s+(\w+)", re.IGNORECASE)
MANIFEST = "manifest.json"
GIT_AND_MODEL = ("provider", "model", "commit", "dirty", "diff")
PROMPTS = Path(prompts.__file__).parent
# The config.py values a run's result depends on (not timeouts, retries or cache ages).
CONFIG_KEYS = ("AGENT_MAX_STEPS", "AGENT_SELF_REVIEW_PASSES", "AGENT_CRITIC_ROUNDS", "FIND_COMPANY_MAX_MATCHES",
               "FIND_COMPANY_MIN_SCORE", "FINANCIALS_DEFAULT_YEARS", "LIST_FILINGS_MAX_RESULTS", "SECTION_PAGE_CHARS",
               "SECTION_HEADING_MAX_CHARS", "SECTION_SEARCH_MAX_CHUNKS", "SCREEN_DEFAULT_TOP_K", "SCREEN_FRAME_LAG_DAYS",
               "PRICE_PROVIDERS", "PRICE_DEFAULT_LOOKBACK_DAYS", "PRICE_CLOSE_AVAILABLE_HOUR", "TRADING_DAYS_PER_YEAR",
               "CHECKER_ALLOWED_NUMBER_PATTERNS", "REPORT_DECIMALS")


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def git_commit() -> str | None:
    try:
        done = subprocess.run(["git", "rev-parse", "HEAD"], cwd=config.PROJECT_ROOT, capture_output=True, text=True)
    except OSError:
        return None
    return done.stdout.strip() if done.returncode == 0 else None


def git_changes() -> tuple[bool | None, str | None]:
    """Whether tracked files differ from the commit, and a hash of `git diff HEAD`, so an uncommitted edit counts too."""
    try:
        done = subprocess.run(["git", "diff", "HEAD", "--no-ext-diff"], cwd=config.PROJECT_ROOT, capture_output=True)
    except OSError:
        return None, None
    if done.returncode != 0:
        return None, None
    return bool(done.stdout), hashlib.sha256(done.stdout).hexdigest()


def manifest(settings, cases: list[dict], case_dir: Path) -> dict:
    """What this batch's results depend on, besides the data: the model, prompts, config, case files and code."""
    dirty, diff = git_changes()
    return {"provider": settings and settings.provider, "model": settings and settings.model,
            "prompts": {path.name: digest(path) for path in sorted(PROMPTS.glob("*.md"))},
            "config": json.loads(json.dumps({key: getattr(config, key) for key in CONFIG_KEYS})),
            "cases": {case["id"]: digest(case_dir / f"{case['id']}.yaml") for case in cases}, "commit": git_commit(),
            "dirty": dirty, "diff": diff}


def check_manifest(batch: Path, current: dict) -> str | None:
    """Writes a new batch's manifest, or adds new cases to an old one. Returns why a resume is refused, if it is."""
    path = batch / MANIFEST
    if not path.is_file():
        if score.read_index(batch):
            return (f"{batch} has runs but no {MANIFEST} (it was made before batches kept one), so a resume can't "
                    "check that it ran with the same set-up. Score it with --rescore, or start a new batch with "
                    "another --out.")
        path.write_text(json.dumps(current, indent=1), encoding="utf-8")
        return None
    saved, problems = json.loads(path.read_text(encoding="utf-8")), []
    for key in GIT_AND_MODEL:  # None: not known then (an A-only batch, an older manifest) or now
        if saved.get(key) is not None and current[key] is not None and saved[key] != current[key]:
            problems.append("uncommitted changes (git diff) differ" if key == "diff"
                            else f"{key}: {saved[key]} then, {current[key]} now")
    for key in ("prompts", "config"):
        old = saved.get(key) or {}
        if changed := sorted(k for k in old.keys() | current[key].keys() if old.get(k) != current[key].get(k)):
            problems.append(f"{key}: {', '.join(changed)} changed")
    old_cases = saved.get("cases") or {}
    if changed := [i for i in current["cases"] if i in old_cases and old_cases[i] != current["cases"][i]]:
        problems.append(f"case files: {', '.join(changed)} changed")
    if problems:
        return (f"{batch} ran with another set-up, so resuming it would mix results: {'; '.join(problems)}. "
                "Start a new batch with another --out.")
    known = {key: current[key] for key in GIT_AND_MODEL if saved.get(key) is None}
    path.write_text(json.dumps(saved | known | {"cases": old_cases | current["cases"]}, indent=1), encoding="utf-8")
    return None


@contextmanager
def injected(injection: dict | None):
    """While a prompt-injection case runs, append its text to the last paragraph the target tool returns from the
    target filing and Item (REFERENCE §8), in the result and its record alike. Yields a one-item list counting how
    often the text was appended: 0 means the agent never read the target."""
    count = [0]
    if not injection:
        yield count
        return
    original = registry.TOOLS[injection["tool"]]
    accession, item = ACCESSION.search(injection["target"]), ITEM.search(injection["target"])

    def run(args, context: ToolContext):
        result = original.run(args, context)
        data = result.data if isinstance(result.data, dict) else {}
        chunks = data.get("chunks")
        if (chunks and (not accession or (data.get("filing") or {}).get("accession") == accession[0])
                and (not item or str(data.get("section", "")).endswith(f"item_{item[1].lower()}"))):
            chunks[-1]["text"] += "\n\n" + injection["text"]
            if chunks[-1]["id"] in context.records:
                context.records[chunks[-1]["id"]]["text"] = chunks[-1]["text"]
            count[0] += 1
        return result

    registry.TOOLS[injection["tool"]] = replace(original, run=run)
    try:
        yield count
    finally:
        registry.TOOLS[injection["tool"]] = original


def append(batch: Path, entry: dict):
    with (batch / "runs.jsonl").open("a", encoding="utf-8") as file:
        file.write(json.dumps(entry) + "\n")


def ended(batch: Path) -> set[tuple]:
    """(case, condition, repeat) of the batch's runs whose trace has a run_end."""
    return {(e["case"], e["condition"], e["repeat"]) for e in score.read_index(batch)
            if (batch / e["trace"]).is_file() and (found := summary(batch / e["trace"])) and found["status"]}


def run_case(case: dict, condition: str, repeat: int, batch: Path, client, settings, sec):
    trace = Trace.new(batch / "traces", echo=cli.progress)
    entry = {"case": case["id"], "condition": condition, "repeat": repeat, "trace": f"traces/{trace.path.name}",
             "run_id": trace.run_id, "injected": None}
    append(batch, entry)
    cutoff = datetime.combine(case["cutoff"], time.max, timezone.utc)
    if condition == "A":
        baseline_a.run(case, cutoff, trace, batch / "baseline_a")
        return
    with injected(case.get("injection")) as count:
        context = ToolContext(cutoff=cutoff, sec=sec, historical=True)  # every case has its own past cutoff
        result = cli.CONDITIONS[condition](case["question"], client, settings, context, trace=trace)
    if case.get("injection"):
        append(batch, entry | {"injected": count[0]})
    cost = result.totals.get("cost")
    print(f"   {result.status}, {result.totals['model_calls']} model calls"
          + (f", ${cost:.4f}" if cost is not None else ""), file=sys.stderr)


def pick(cases: dict[str, dict], ids: str | None, split: str) -> list[dict]:
    if not ids:
        return [case for case in cases.values() if case["split"] == split]
    wanted = [i.strip() for i in ids.split(",") if i.strip()]
    if unknown := [i for i in wanted if i not in cases]:
        raise SystemExit(f"No such case: {', '.join(unknown)} (see eval/cases/).")
    return [cases[i] for i in wanted]


def skip_reason(case: dict, condition: str) -> str | None:
    if case["mode"] == "discover":
        return "Discover cases aren't run yet: a case would need its universe"
    return baseline_a.unsupported(case) if condition == "A" else None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run conditions A-D on the evaluation cases, then score them.")
    parser.add_argument("--conditions", metavar="A,B,C,D",
                        help="Conditions to run, comma-separated. B, C and D call the model, so each run costs money.")
    parser.add_argument("--cases", metavar="ID,ID", help="Case IDs, comma-separated (default: every case of --split).")
    parser.add_argument("--split", choices=("dev", "held_out"), default="dev")
    parser.add_argument("--repeats", type=int, default=1, metavar="N",
                        help="Runs per case and condition, to measure randomness (default 1).")
    parser.add_argument("--out", type=Path, metavar="FOLDER", help="Batch folder (default: a new one in data/eval/).")
    parser.add_argument("--rescore", type=Path, metavar="BATCH", help="Only score a saved batch, offline.")
    parser.add_argument("--case-dir", type=Path, default=score.CASES, help="The case folder (default: eval/cases).")
    args = parser.parse_args(argv)
    if args.rescore:
        return score.main([str(args.rescore), "--cases", str(args.case_dir)])
    conditions = [c.strip().upper() for c in (args.conditions or "").split(",") if c.strip()]
    if not conditions or set(conditions) - set(CONDITIONS):
        parser.error("--conditions takes some of A, B, C and D, e.g. --conditions B")
    if args.repeats < 1:
        parser.error("--repeats must be at least 1")
    cli.utf8_console()
    chosen = pick(score.load_cases(args.case_dir), args.cases, args.split)
    batch = args.out or config.eval_dir() / datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    batch.mkdir(parents=True, exist_ok=True)
    load_dotenv(config.PROJECT_ROOT / ".env", override=False, interpolate=False, encoding="utf-8-sig")
    settings = None
    if set(conditions) - {"A"} and (settings := cli.model_settings()) is None:
        return 2
    if refused := check_manifest(batch, manifest(settings, chosen, args.case_dir)):
        print(refused, file=sys.stderr)
        return 2
    done = ended(batch)
    with cli.sec_client() as sec, (cli.model_client(settings) if settings else nullcontext()) as client:
        for case in chosen:
            for condition in conditions:
                if reason := skip_reason(case, condition):
                    print(f"Skipped {case['id']} for {condition}: {reason}.", file=sys.stderr)
                    continue
                for repeat in range(1, args.repeats + 1):
                    if (case["id"], condition, repeat) in done:
                        print(f"Skipped {case['id']} {condition}{repeat}: it already ended in {batch}.", file=sys.stderr)
                        continue
                    print(f"\n== {case['id']}: condition {condition}, repeat {repeat}", file=sys.stderr)
                    try:
                        run_case(case, condition, repeat, batch, client, settings, sec)
                    except Exception as exc:  # one broken run mustn't stop the batch; it scores as crashed
                        print(f"   crashed: {type(exc).__name__}: {exc}", file=sys.stderr)
    print(f"\nBatch saved in {batch}", file=sys.stderr)
    return score.main([str(batch), "--cases", str(args.case_dir)])


if __name__ == "__main__":
    sys.exit(main())
