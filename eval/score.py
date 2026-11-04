"""Score an evaluation batch against the cases' gold answers and print REFERENCE §7's tables, offline.

A batch is the folder eval/run_eval.py writes: runs.jsonl (one line per run: case, condition, repeat, trace file)
and the traces. Scoring reads only the cases and the records each trace froze, so it needs no network and no model,
and a saved batch can be rescored at any time:  python eval/score.py data/eval/<batch>

The rules, simple on purpose:
- Shown numbers are the records behind the final report's {fact:ID}/{calc:ID} placeholders (for A, its metrics).
  Typed figures don't count as gold: the checker already flags them, and no record backs them.
- A gold item is correct when a shown number measures the gold's `metric`, is of the same company, equals it within
  tolerance and has the same period end and kind (annual, interim or a balance). Tolerance: the case's `tolerance`,
  else half a unit in the gold's last digit (1577 -> 0.5). The gold's unit converts to the record's ("USD millions"
  -> USD x 10^6, "percent" -> ratio / 100). A metric is a get_financials metric (revenue), its growth or CAGR
  (revenue_growth), a ratio of two (operating_income_to_revenue) or another calculate formula (fcf); a metric no tool
  measures (cost_of_goods_sold), or a gold item without one, needs review.
- The right size with the other sign, the right value for another period end or kind, or a match whose company
  can't be confirmed (no CIK on the record or the case) needs review. Anything else is missing: left out or wrong
  (the case's must_not lines name the wrong figures to look for).
- A report answers when it shows at least one number, or a section's claim has a figure the checker flagged as
  typed (limitations say what is missing, so theirs don't count). `answer` must answer, `not_available` must not,
  `answer_or_abstain` may do either, and an allowed abstention needs no gold. A placeholder whose ID no tool returned
  needs review.
- A run passes when it ended with a report (finished or stopped at limit), its behaviour is right and every gold item
  is correct. must_mention and must_not lines, claim support and whether an objection was valid need a person: they
  are listed as "needs review", never guessed.
"""
import argparse
import json
import re
import sys
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

import yaml

from research_assistant.agents import evidence
from research_assistant.agents.checker import PLACEHOLDER, lookup
from research_assistant.agents.draft import SECTIONS
from research_assistant.data.sec_facts import CONCEPTS
from research_assistant.tools.calculate import ROLES

import score_tables

CASES = Path(__file__).resolve().parent / "cases"
# A gold unit -> the unit tool records use, and how many record units one gold unit is.
UNITS = {"USD millions": ("USD", Decimal(10) ** 6), "TWD millions": ("TWD", Decimal(10) ** 6),
         "USD": ("USD", Decimal(1)), "percent": ("ratio", Decimal("0.01"))}
ENDED = ("finished", "stopped_at_limit")  # run statuses that hand in a report
AGENTS = ("B", "C", "D")  # conditions whose traces hold a draft and calculate records to recheck
# The checker's flags for a typed figure and for a placeholder whose ID no tool returned (checker.fill).
TYPED = re.compile(r"'[^']*' is typed, not a \{fact:ID\}/\{calc:ID\} placeholder")
UNRESOLVED = re.compile(r"(\{(?:fact|calc):[^}]*\}) is not an ID any tool returned")
CHANGES = {"growth": "current", "cagr": "last", "change_pp": "current"}  # formula -> the input it measures
ANNUAL_DAYS = 300  # a flow covering at least this many days is a fiscal year's (52/53 weeks), else interim


def load_cases(folder: Path = CASES) -> dict[str, dict]:
    cases = (yaml.safe_load(path.read_text(encoding="utf-8")) for path in sorted(folder.glob("*.yaml")))
    return {case["id"]: case for case in cases}


def read_index(batch: Path) -> list[dict]:
    """The batch's runs, the latest line per (case, condition, repeat): a rerun after a crash replaces the old one."""
    path, latest = batch / "runs.jsonl", {}
    for line in path.read_text(encoding="utf-8").splitlines() if path.is_file() else []:
        if line.strip():
            entry = json.loads(line)
            latest[(entry["case"], entry["condition"], entry["repeat"])] = entry
    return list(latest.values())


def tolerance(item: dict) -> Decimal:
    """In the gold's own unit: the case's tolerance, else half a unit in the last digit written."""
    if "tolerance" in item:
        return Decimal(str(item["tolerance"]))
    return Decimal("0.5").scaleb(-len(str(item["value"]).partition(".")[2]))


def shown(texts: list[str], records: dict[str, dict]) -> list[dict]:
    """The fact and calc records behind the placeholders in these texts, each once, in order."""
    found = {}
    for text in texts:
        for match in PLACEHOLDER.finditer(text):
            record = lookup(records, match[2], match[1])
            if record and record.get("kind") in ("fact", "calc") and record.get("value") is not None:
                found[record["id"]] = record
    return list(found.values())


def draft_texts(draft: dict) -> list[str]:
    claims = [claim for key, _ in SECTIONS for claim in draft.get(key) or []]
    return [c if isinstance(c, str) else c.get("text", "") for c in claims] + list(draft.get("limitations") or [])


def measure(record: dict, records: dict[str, dict]) -> str | None:
    """What a record measures, in the words of a gold item's `metric` (see the module rules)."""
    if record.get("kind") == "fact":
        return record.get("metric")
    formula, inputs = record.get("formula"), record.get("inputs")
    if not isinstance(inputs, dict):  # A's calculations spell their formula out: "operating_income / revenue"
        a, _, b = str(formula).partition(" / ")
        return f"{a}_to_{b}" if b else formula

    def of(role: str) -> str | None:
        found = records.get(inputs.get(role))
        return measure(found, records) if found else None
    if formula in CHANGES:
        return (base := of(CHANGES[formula])) and f"{base}_{formula}"
    if formula == "ratio":
        return (a := of("numerator")) and (b := of("denominator")) and f"{a}_to_{b}"
    return formula


def period_kind(record: dict, records: dict[str, dict]) -> str | None:
    """instant (a balance), annual or interim; a calculation takes its measured input's kind. None if unknown."""
    if record.get("kind") == "fact":
        if not record.get("start"):
            return "instant"
        days = (date.fromisoformat(record["end"]) - date.fromisoformat(record["start"])).days
        return "annual" if days >= ANNUAL_DAYS else "interim"
    role, inputs = {**CHANGES, "ratio": "numerator"}.get(record.get("formula")), record.get("inputs")
    found = records.get(inputs.get(role)) if role and isinstance(inputs, dict) else None
    return period_kind(found, records) if found else None


def _base(metric: str) -> list[str]:
    """The get_financials metrics a gold metric is built from: revenue_growth -> [revenue]."""
    for suffix in ("_" + formula for formula in CHANGES):
        metric = metric.removesuffix(suffix)
    return metric.split("_to_")


def judgeable(metric: str) -> bool:
    parts = _base(metric)
    return metric in ROLES or (len(parts) <= 2 and all(part in CONCEPTS for part in parts))


def gold_kind(item: dict) -> str | None:
    concept = CONCEPTS.get(_base(item["metric"])[0])
    if concept and concept.kind in ("instant", "cover"):
        return "instant"
    return "annual" if str(item.get("fiscal_period", "")).startswith("FY") else None


def judge(item: dict, cik: int | None, numbers: list[dict], records: dict[str, dict]) -> dict:
    """One gold item against the numbers a report shows: correct, needs review or missing (see the module rules).
    `records` are the run's frozen records, to see what a calculation's inputs measure."""
    outcome = {"name": item["name"], "outcome": "missing", "record": None, "note": None}
    if item["unit"] not in UNITS:
        return outcome | {"outcome": "needs review", "note": f"No automatic rule for the unit {item['unit']!r}."}
    if not item.get("metric"):
        return outcome | {"outcome": "needs review", "note": "The gold item names no metric, so no record can match it."}
    if not judgeable(item["metric"]):
        return outcome | {"outcome": "needs review", "note": f"No tool record measures {item['metric']!r}."}
    unit, scale = UNITS[item["unit"]]
    gold, slack = Decimal(str(item["value"])) * scale, tolerance(item) * scale
    kind, near = gold_kind(item), None
    for record in numbers:
        if record.get("unit") != unit or measure(record, records) != item["metric"]:
            continue  # total assets never count as revenue, whatever the value
        if record.get("cik") and cik and int(record["cik"]) != cik:
            continue
        value = Decimal(str(record["value"]))
        if abs(value - gold) <= slack:
            found = period_kind(record, records)
            if record.get("end") != str(item["period_end"]):
                near = near or (record["id"], f"{record['id']} has the value but its period ends {record.get('end')}, "
                                              f"not {item['period_end']}.")
            elif kind and found and kind != found:
                near = near or (record["id"], f"{record['id']} has the value but is an {found} figure, not {kind}.")
            elif not (record.get("cik") and cik):
                near = near or (record["id"], f"{record['id']} matches, but its company can't be confirmed (no CIK "
                                              f"on the {'case' if not cik else 'record'}).")
            else:
                return outcome | {"outcome": "correct", "record": record["id"]}
        elif abs(value + gold) <= slack:
            near = near or (record["id"], f"{record['id']} has the size but the other sign.")
    if near:
        return outcome | {"outcome": "needs review", "record": near[0], "note": near[1]}
    return outcome


def first_draft(run: evidence.SavedRun) -> dict | None:
    """The lead's last draft before the critic's first review (D): what C would have handed in."""
    lead, draft = run.start.get("lead"), None
    for event in run.events:
        if event["kind"] == "critic_start":
            return draft
        if event["kind"] == "finish" and event.get("valid") and event.get("agent") == lead:
            draft = event["output"]
    return None


def numbers(end: dict, records: dict[str, dict]) -> list[dict]:
    if end.get("draft") is not None:
        return shown(draft_texts(end["draft"]), records)
    return [records[i] for i in end.get("shown") or [] if i in records]  # A writes its metrics' records here


def score_run(case: dict, entry: dict, batch: Path) -> dict:
    row = {"case": case["id"], "condition": entry["condition"], "repeat": entry["repeat"], "trace": entry["trace"],
           "injected": entry.get("injected"), "status": "crashed", "error": None, "gold": [], "gold_before": None,
           "ended": False, "answered": False, "abstained": False, "behaviour_ok": False, "passed": False,
           "support": None, "objections": [],
           "totals": None, "minutes": None, "recheck": [],
           "review": [f"Must mention: {line}" for line in case["expected"].get("must_mention", [])]
           + [f"Must not: {line}" for line in case["expected"].get("must_not", [])]}
    path = batch / entry["trace"]
    try:
        run = evidence.load(path) if path.is_file() else None
    except ValueError:  # a half-written last line: the run crashed while writing
        run = None
    if run is None or run.start is None or run.end is None:  # its gold counts as missing, so a crash can't help
        return row | {"error": "The trace has no run_end: the run crashed, or is still going.",
                      "gold": [{"name": item["name"], "outcome": "missing", "record": None, "note": "crashed"}
                               for item in case["gold"]]}
    end, ciks = run.end, {company["ticker"]: company["cik"] for company in case["companies"]}
    final = numbers(end, run.records)
    gold = [judge(item, ciks.get(item["ticker"]), final, run.records) for item in case["gold"]]
    if (draft := first_draft(run)) is not None:
        before = shown(draft_texts(draft), run.records)
        row["gold_before"] = [judge(item, ciks.get(item["ticker"]), before, run.records) for item in case["gold"]]
    flags = (end.get("report") or {}).get("flags") or []
    typed = [f for f in flags if TYPED.match(f["problem"]) and not f["where"].startswith("limitations")]
    row["review"] += [f"Unresolved placeholder in {f['where']}: {m[1]}" for f in flags
                      if (m := UNRESOLVED.match(f["problem"]))]
    behaviour, answered = case["expected"]["behaviour"], bool(final or typed)
    behaviour_ok = {"answer": answered, "not_available": not answered}.get(behaviour, True)
    abstained = behaviour == "answer_or_abstain" and not answered
    row["review"] += [f"Gold {g['name']}: {g['note']}" for g in gold if g["outcome"] == "needs review"]
    ended = end["status"] in ENDED
    return row | {
        "status": end["status"], "error": end.get("error"), "gold": gold, "ended": ended, "answered": answered,
        "abstained": abstained, "behaviour_ok": behaviour_ok,
        "passed": ended and behaviour_ok and (abstained or all(g["outcome"] == "correct" for g in gold)),
        "support": support(end.get("report") or {}), "totals": end.get("totals"),
        "minutes": round((datetime.fromisoformat(end["at"]) - datetime.fromisoformat(run.start["at"])).total_seconds()
                         / 60, 2),
        "objections": [{key: o.get(key) for key in ("id", "issue", "material", "outcome")}
                       for o in end.get("objections") or []],
        # A run whose tools found nothing (an unknown ticker) has nothing to recheck.
        "recheck": evidence.recheck(path).problems if entry["condition"] in AGENTS and run.records else []}


def support(report: dict) -> dict:
    """Citation validity, from the checker's flags. Whether the evidence really supports a claim is for a person."""
    sections = report.get("sections") or {}
    claims = [claim for key, _ in SECTIONS for claim in sections.get(key) or []]
    return {"claims": len(claims), "cited": sum(not c["flags"] for c in claims),
            "uncited": sum(not c["citations"] for c in claims),
            "central": sum(c.get("materiality") == "central" for c in claims),
            "abstained": sum(not sections.get(key) for key, _ in SECTIONS)}


def score(batch: Path, cases: dict[str, dict]) -> list[dict]:
    rows = []
    for entry in read_index(batch):
        if entry["case"] not in cases:
            print(f"Skipped {entry['case']}: no such case in the cases folder.", file=sys.stderr)
            continue
        rows.append(score_run(cases[entry["case"]], entry, batch))
    return rows


def write(batch: Path, rows: list[dict], cases: dict[str, dict]) -> str:
    """scores.md (the tables), scores.json (one row per run) and each run's report for the human checks."""
    text = score_tables.markdown(rows, cases)
    (batch / "scores.md").write_text(text, encoding="utf-8")
    (batch / "scores.json").write_text(json.dumps(rows, indent=1, ensure_ascii=False), encoding="utf-8")
    folder = batch / "reports"
    folder.mkdir(exist_ok=True)
    for row in rows:
        run = evidence.load(batch / row["trace"]) if row["status"] != "crashed" else None
        if run and run.end:
            name = f"{row['case']}--{row['condition']}{row['repeat']}.md"
            (folder / name).write_text(run.end.get("markdown") or "", encoding="utf-8")
    return text


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Score a saved evaluation batch offline and print the tables.")
    parser.add_argument("batch", type=Path, help="A batch folder written by eval/run_eval.py.")
    parser.add_argument("--cases", type=Path, default=CASES, help="The case folder (default: eval/cases).")
    args = parser.parse_args(argv)
    for stream in (sys.stdout, sys.stderr):  # Windows consoles default to a legacy code page
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    if not (args.batch / "runs.jsonl").is_file():
        print(f"{args.batch} has no runs.jsonl: give a folder eval/run_eval.py wrote.", file=sys.stderr)
        return 2
    cases = load_cases(args.cases)
    print(write(args.batch, score(args.batch, cases), cases))
    return 0


if __name__ == "__main__":
    sys.exit(main())
