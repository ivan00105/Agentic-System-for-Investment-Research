"""REFERENCE §7's tables as Markdown, built from score.py's rows (one per run)."""
import math
from collections import Counter
from statistics import median

from research_assistant.agents.draft import SECTIONS

ORDER = ("A", "B", "C", "D")


def markdown(rows: list[dict], cases: dict[str, dict]) -> str:
    parts = ["# Evaluation scores",
             f"{len(rows)} runs of {len({r['case'] for r in rows})} cases. Small samples are exploratory "
             "(REFERENCE §7): read these as counts, not as significant differences.",
             "## Accuracy", accuracy(rows), "## Support", support(rows), "## Critic: fixes vs damage (D vs C)",
             critic(rows), "## Cost, tokens and latency", cost(rows), "## Failures", failures(rows),
             "## Needs review", review(rows, cases)]
    return "\n\n".join(parts) + "\n"


def table(head: list[str], body: list[list]) -> str:
    if not body:
        return "(none)"
    def cell(value) -> str:
        return str(value).replace("|", "\\|").replace("\n", " ")
    lines = ["| " + " | ".join(head) + " |", "|" + "---|" * len(head)]
    return "\n".join(lines + ["| " + " | ".join(cell(v) for v in row) + " |" for row in body])


def by_condition(rows: list[dict]) -> list[tuple[str, list[dict]]]:
    names = sorted({r["condition"] for r in rows}, key=lambda c: (ORDER.index(c) if c in ORDER else len(ORDER), c))
    return [(name, [r for r in rows if r["condition"] == name]) for name in names]


def share(part: int, whole: int) -> str:
    return f"{part}/{whole} ({part / whole:.0%})" if whole else "-"


def accuracy(rows: list[dict]) -> str:
    parts = [summary(rows)]
    a_cases = {r["case"] for r in rows if r["condition"] == "A"}
    if a_cases:
        parts += [f"On the {len(a_cases)} cases A supports, the fair comparison with the old pipeline:",
                  summary([r for r in rows if r["case"] in a_cases])]
    body = [[r["case"], r["condition"], r["repeat"], r["status"],
             f"{sum(g['outcome'] == 'correct' for g in r['gold'])}/{len(r['gold'])}" if r["gold"] else "-",
             "-" if r["status"] == "crashed" else
             ("answered" if r["answered"] else "abstained") + ("" if r["behaviour_ok"] else " (wrong)"),
             "yes" if r["passed"] else "no", len(r["review"])] for r in rows]
    parts += ["Per run:", table(["Case", "Condition", "Repeat", "Status", "Gold correct", "Behaviour", "Passed",
                                  "Needs review"], body)]
    return "\n\n".join(parts)


def summary(rows: list[dict]) -> str:
    body = []
    for condition, group in by_condition(rows):
        gold = [g for r in group for g in r["gold"]]
        body.append([condition, len(group), share(sum(r["passed"] for r in group), len(group)),
                     share(sum(g["outcome"] == "correct" for g in gold), len(gold)),
                     share(sum(r["behaviour_ok"] for r in group), len(group)), sum(len(r["review"]) for r in group)])
    return table(["Condition", "Runs", "Passed", "Gold items correct", "Right behaviour", "Needs review"], body)


def support(rows: list[dict]) -> str:
    body = []
    for condition, group in by_condition(rows):
        found = [r["support"] for r in group if r["support"]]
        claims = sum(s["claims"] for s in found)
        body.append([condition, len(found), claims, share(sum(s["cited"] for s in found), claims),
                     sum(s["uncited"] for s in found), f"{sum(s['abstained'] for s in found)}/{len(found) * len(SECTIONS)}",
                     sum(s["central"] for s in found)])
    return (table(["Condition", "Reports", "Claims", "Cited, no checker flag", "No citation", "Sections abstained",
                   "Central claims"], body)
            + "\n\nCitation validity is automatic (the checker's flags). Whether the cited evidence really supports a "
              "claim needs review: a person judges a sample of the central claims.")


def flips(before: list[dict], after: list[dict]) -> tuple[int, int]:
    """Gold items not correct before and correct after (fixed), and correct before but not after (damaged)."""
    pairs = list(zip(before, after, strict=True))
    return (sum(b["outcome"] != "correct" and a["outcome"] == "correct" for b, a in pairs),
            sum(b["outcome"] == "correct" and a["outcome"] != "correct" for b, a in pairs))


def critic(rows: list[dict]) -> str:
    d_rows = [r for r in rows if r["condition"] == "D" and r["status"] != "crashed"]
    if not d_rows:
        return "No D runs in this batch."
    c_runs = {(r["case"], r["repeat"]): r for r in rows if r["condition"] == "C" and r["status"] != "crashed"}
    body = []
    for r in d_rows:
        outcomes = Counter(o["outcome"] for o in r["objections"])
        fixed, damaged = flips(r["gold_before"], r["gold"]) if r["gold_before"] is not None else ("-", "-")
        c = c_runs.get((r["case"], r["repeat"]))
        better, worse = flips(c["gold"], r["gold"]) if c else ("no C run", "no C run")
        body.append([r["case"], r["repeat"], len(r["objections"]), outcomes["defended"], outcomes["corrected"],
                     outcomes["withdrawn"], outcomes["unresolved"], fixed, damaged, better, worse])
    raised = sum(len(r["objections"]) for r in d_rows)
    return (table(["Case", "Repeat", "Objections", "Defended", "Corrected", "Withdrawn", "Unresolved", "Fixed",
                   "Damaged", "D right, C wrong", "D wrong, C right"], body)
            + "\n\nFixed and Damaged compare the draft the critic first saw with the final report, on the same "
              "evidence; '-' means the critic never ran. The C columns compare with the C run of the same case and "
              f"repeat, which retrieved its own evidence. Whether each objection was valid needs review ({raised} "
              f"objections in {len(d_rows)} runs).")


def cost_row(condition: str, done: list[dict]) -> list:
    if not done:
        return [condition, 0] + ["-"] * 9
    total = {key: sum(r["totals"].get(key) or 0 for r in done)
             for key in ("model_calls", "tool_calls", "prompt_tokens", "cached_tokens", "completion_tokens")}
    per_run = {key: f"{value / len(done):,.0f}" for key, value in total.items()}
    costs = [r["totals"]["cost"] for r in done if r["totals"].get("cost") is not None]
    minutes = sorted(r["minutes"] for r in done)
    prompt = total["prompt_tokens"]
    return [condition, len(done), per_run["model_calls"], per_run["tool_calls"], per_run["prompt_tokens"],
            f"{total['cached_tokens'] / prompt:.0%}" if prompt else "-", per_run["completion_tokens"],
            f"${sum(costs) / len(costs):.4f}" if costs else "-", f"${sum(costs):.4f}" if costs else "-",
            f"{median(minutes):.1f}", f"{minutes[math.ceil(0.95 * len(minutes)) - 1]:.1f}"]


def cost(rows: list[dict]) -> str:
    body = [cost_row(condition, [r for r in group if r["totals"]]) for condition, group in by_condition(rows)]
    return (table(["Condition", "Runs", "Model calls / run", "Tool calls / run", "Prompt tokens / run", "Cached",
                   "Completion tokens / run", "Cost / run", "Total cost", "Median minutes", "p95 minutes"], body)
            + "\n\nModel calls are the steps. Cost is what the provider billed (OpenRouter's usage.cost, cache discount "
              "included); '-' where it reported none (A makes no model call). p95 of fewer than 20 runs is about the "
              "slowest run.")


def problems(row: dict) -> list[str]:
    if row["status"] == "crashed":
        return [f"crashed: {row['error']}"]
    found = [] if row["ended"] else [row["status"] + (f": {row['error']}" if row["error"] else "")]
    if not row["behaviour_ok"]:
        found.append("shows numbers, but no data exists for this case" if row["answered"] else "shows no number")
    if not row["abstained"]:
        found += [f"{g['name']}: {g['outcome']}" for g in row["gold"] if g["outcome"] != "correct"]
    found += [f"recheck: {problem}" for problem in row["recheck"]]
    if row["injected"] == 0:
        found.append("the injected text never reached the agent (it didn't read the target section)")
    return found


def failures(rows: list[dict]) -> str:
    rates = [f"{condition}: {share(sum(not r['ended'] for r in group), len(group))}"
             for condition, group in by_condition(rows)]
    body = [[r["case"], r["condition"], r["repeat"], "; ".join(found)] for r in rows if (found := problems(r))]
    return (table(["Case", "Condition", "Repeat", "What went wrong"], body)
            + "\n\nRuns that ended without a report (failed, stopped or crashed): " + ", ".join(rates) + ".")


def review(rows: list[dict], cases: dict[str, dict]) -> str:
    """What a person checks per case: its must_mention/must_not lines and any gold item the rules couldn't settle,
    with the reports to read (written to the batch's reports/ folder)."""
    parts = []
    for case_id in dict.fromkeys(r["case"] for r in rows):
        runs = [r for r in rows if r["case"] == case_id and r["status"] != "crashed"]
        expected = cases[case_id]["expected"]
        lines = [f"- Must mention: {line}" for line in expected.get("must_mention", [])]
        lines += [f"- Must not: {line}" for line in expected.get("must_not", [])]
        lines += [f"- {r['condition']}{r['repeat']}, {line}" for r in runs for line in r["review"]
                  if line.startswith("Gold ")]
        if runs and lines:
            reports = ", ".join(f"reports/{case_id}--{r['condition']}{r['repeat']}.md" for r in runs)
            parts.append(f"### {case_id}\n\n{cases[case_id]['question']}\n\n" + "\n".join(lines)
                         + f"\n\nReports: {reports}")
    return "\n\n".join(parts) or "Nothing to review."
