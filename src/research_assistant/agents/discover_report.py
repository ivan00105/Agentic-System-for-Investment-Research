"""Render a Discover run as Markdown: the screen spec, counts, the shortlist with each pick's acceptance test and
research summary, the candidates not picked, and each pick's full cited report."""
from .acceptance import UNITS, threshold
from .checker import format_value
from .discover_spec import SOURCES
from .report import RUN_STATUS, describe

COUNTS = (("screened", "Screened"), ("eligible", "Passed the screen"), ("ranked", "Ranked"),
          ("checked", "Checked on the latest 10-K"), ("rejected", "Rejected by the check"),
          ("researched", "Researched"), ("failed", "Research failed"), ("replaced", "Replaced"),
          ("returned", "Returned"))
SHOWN = ("summary", "bull_case", "bear_case", "risks")  # the parts of a pick's report repeated in the shortlist


def spec_lines(spec, sources: dict[str, str], universe, top_k: int, condition: str) -> list[str]:
    """The screen spec as the user sees it before anything runs (REFERENCE §4 rule 1)."""
    screen = [threshold(f.metric, f.op, f.value) for f in spec.filters]
    if spec.sic_prefixes:
        screen.append(f"SIC industry code starting with {' or '.join(spec.sic_prefixes)}")
    lines = [f"Universe: {universe.name}, {len(universe.ciks)} companies ({len(universe.members)} tickers) from "
             f"{universe.source}, as of {universe.as_of}: a declared list, not the whole market. {universe.note}",
             "Screen, on SEC annual data for the latest complete calendar year: " + ("; ".join(screen) or "no filters"),
             f"Ranked by {spec.rank_by.replace('_', ' ')}, {'highest' if spec.descending else 'lowest'} first; "
             f"top {top_k}.",
             "Checked again on each candidate's latest 10-K before its research"
             + (", with its latest close: " + "; ".join(threshold(c.metric, c.op, c.value) for c in spec.price_checks)
                if spec.price_checks else ".")]
    lines += [f'"{t.term}" read as: {t.definition} ({SOURCES[sources.get(t.term, "assumed")]})' for t in spec.terms]
    lines += [f"Not checked: {text}" for text in spec.not_covered]
    return lines + [f"Each pick is researched by condition {condition}."]


def render(*, question, status, cutoff, model, run_id, error, condition, universe, found, top_k, counts,
           candidates, records, notes) -> str:
    lines = [f"# {question}", "", f"- Mode: Discover over {universe.name}", f"- Run status: {RUN_STATUS[status]}",
             f"- Cutoff: {cutoff}", f"- Research: condition {condition}", f"- Model: {model}", f"- Run: {run_id}"]
    lines += [f"- Error: {error}"] if error else []
    if found.spec is not None:
        lines += ["", "## Screen spec", ""] + [f"- {line}" for line in
                                                spec_lines(found.spec, found.sources, universe, top_k, condition)]
    if counts:
        lines += ["", "## Counts", "", "| " + " | ".join(label for _, label in COUNTS) + " |",
                  "|" + "---|" * len(COUNTS), "| " + " | ".join(str(counts[key]) for key, _ in COUNTS) + " |"]
    picks = [c for c in candidates if c.outcome == "picked"]
    if counts:
        lines += ["", "## Shortlist", ""] + ([] if picks else ["- No candidate passed. See the candidates below."])
    cited: list[str] = []
    for n, c in enumerate(picks, 1):
        lines += [f"### {n}. {_who(c)}", ""] + _candidate(c, cited)
        sections = c.run.report.sections
        for key in SHOWN:
            heading = key.replace("_", " ").capitalize()
            lines += [f"- {heading} ({c.run.report.section_status(key)}):"] + [
                f"  - {claim.text}" + (" (qualified: see its report's flags)" if claim.flags else "")
                for claim in sections[key]] + (["  - Nothing to report."] if not sections[key] else [])
        lines.append("")
    others = [c for c in candidates if c.outcome in ("rejected", "research failed")]
    if others:
        lines += ["## Candidates not picked", ""]
        for c in others:
            lines += [f"### {_who(c)}: {c.outcome}", ""] + _candidate(c, cited) + [""]
    if notes:
        lines += ["## Limitations", ""] + [f"- {note}" for note in notes] + [""]
    if cited:
        lines += ["## Sources of the checks", ""] + [f"- {describe(records[i]).rstrip()}" for i in _with_inputs(
            cited, records)] + [""]
    for n, c in enumerate(picks, 1):
        report = c.run.markdown.splitlines()
        start = next((i for i, line in enumerate(report) if line.startswith("- Run status:")), 0)  # after the brief
        lines += [f"## Research report {n}: {c.name}", ""] + [
            ("#" + line if line.startswith("#") else line) for line in report[start:]]
    return "\n".join(lines).rstrip() + "\n"


def _with_inputs(ids: list[str], records: dict[str, dict]) -> list[str]:
    """The cited records and every record a calculation among them was computed from."""
    found: list[str] = []
    for i in ids:
        if i in records and i not in found:
            found += [i] + [j for j in _with_inputs(list(records[i].get("inputs", {}).values()), records)
                            if j not in found]
    return list(dict.fromkeys(found))


def _who(c) -> str:
    return f"{c.name} ({', '.join(c.tickers) or 'no ticker'}, CIK {c.cik})"


def _candidate(c, cited: list[str]) -> list[str]:
    values = "; ".join(f"{metric.replace('_', ' ')} {_shown(metric, value)}" for metric, value in c.values.items())
    lines = [f"- Screen rank {c.rank} (SEC frames: {values})"]
    if c.verdict:
        lines.append(f"- Check on the latest 10-K: {c.verdict.state}")
        for line in c.verdict.lines:
            lines.append(f"  - {line.state}: {line.text}" + "".join(f" `{i}`" for i in line.ids))
            cited += [i for i in line.ids if i not in cited]
    if c.run:
        lines.append(f"- Research: {RUN_STATUS.get(c.run.status, c.run.status)}, run {c.run.run_id}, trace "
                     f"{c.run.trace_path}" + (f" ({c.run.error})" if c.run.error else ""))
    if c.error:
        lines.append(f"- Research: {c.error}")
    return lines


def _shown(metric: str, value: str | None) -> str:
    return "unknown" if value is None else format_value({"value": value, "unit": UNITS.get(metric, "ratio")})
