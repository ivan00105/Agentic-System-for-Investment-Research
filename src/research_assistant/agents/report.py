"""Render a checked report as Markdown: sections with statuses, numbered sources and checker flags."""
from .checker import CheckedReport, format_value
from .draft import SECTIONS

RUN_STATUS = {
    "finished": "finished",
    "stopped_at_limit": "stopped at limit: the step guard was reached, so this report is partial",
    "failed": "failed",
}


def render(report: CheckedReport, records: dict[str, dict], *, question: str, status: str, cutoff: str,
           model: str | None = None, plan: str | None = None, run_id: str | None = None,
           error: str | None = None) -> str:
    number = {record_id: n for n, record_id in enumerate(report.sources, start=1)}
    lines = [f"# {question}", "", f"- Run status: {RUN_STATUS.get(status, status)}", f"- Cutoff: {cutoff}"]
    lines += [f"- Model: {model}"] if model else []
    lines += [f"- Run: {run_id}"] if run_id else []
    lines += [f"- Error: {error}"] if error else []
    if plan:
        lines += ["", "## Plan", "", plan.strip()]
    for key, heading in SECTIONS:
        lines += ["", f"## {heading} ({report.section_status(key)})", ""]
        claims = report.sections[key]
        lines += [f"- {c.text}{''.join(f' [{number[i]}]' for i in c.citations)}"
                  + (" (qualified: see checker flags)" if c.flags else "") for c in claims] or ["- Nothing to report."]
    if report.limitations:
        lines += ["", "## Limitations", ""] + [f"- {text}" for text in report.limitations]
    if report.flags:
        lines += ["", "## Checker flags", ""] + [f"- {flag.where}: {flag.problem}" for flag in report.flags]
    if report.sources:
        lines += ["", "## Sources", ""] + [f"{number[i]}. {describe(records[i]).rstrip()}" for i in report.sources]
    return "\n".join(lines) + "\n"


def describe(record: dict) -> str:
    """One line saying where a cited record comes from."""
    kind, rid = record.get("kind"), record["id"]
    if kind == "fact":
        period = f"{record['start']} to {record['end']}" if record.get("start") else f"at {record['end']}"
        return (f"`{rid}` {record.get('metric')} = {format_value(record)}, {period} ({record.get('tag')}; "
                f"{record.get('form')} {record.get('accession')}, filed {record.get('filed')}) {record.get('filing_url', '')}")
    if kind == "calc":
        value = format_value(record) if record.get("value") is not None else f"unavailable ({record.get('reason')})"
        inputs = ", ".join(f"{role}=`{i}`" for role, i in record.get("inputs", {}).items())
        period = " to ".join(str(p) for p in (record.get("start"), record.get("end")) if p)
        notes = "; ".join(record.get("notes") or [])
        return f"`{rid}` {record.get('formula')}({inputs}) = {value}, {period}" + (f". {notes}" if notes else "")
    if kind == "chunk":
        return f"`{rid}` {record.get('form')} {record.get('accession')}, {record.get('section')} paragraph {record.get('n')} {record.get('url', '')}"
    if kind == "filing":
        return f"`{rid}` {record.get('form')} filed {record.get('filed')}: {record.get('description') or ''} {record.get('url', '')}"
    if kind == "company":
        return f"`{rid}` {record.get('name')} (CIK {record.get('cik')}, {', '.join(record.get('tickers') or [])})"
    if kind == "prices":
        return f"`{rid}` {record.get('ticker')} daily prices from {record.get('source')}, {record.get('start')} to {record.get('end')}"
    if kind == "check":
        return f"`{rid}` {record.get('fact_id')} checked against the filing: {record.get('verdict')} {record.get('filing_url', '')}"
    return f"`{rid}` {kind} record"
