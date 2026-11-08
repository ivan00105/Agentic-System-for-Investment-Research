"""Render a checked report as Markdown: sections with statuses, the critic's review, numbered sources and flags."""
from .checker import CheckedReport, format_value
from .draft import SECTIONS

RUN_STATUS = {
    "finished": "finished",
    "stopped_at_limit": "stopped at limit: the step guard was reached, so this report is partial",
    "stopped": "stopped: the run was cancelled, so this report is partial",
    "failed": "failed",
}


def render(report: CheckedReport, records: dict[str, dict], *, question: str, status: str, cutoff: str,
           model: str | None = None, plan: str | None = None, run_id: str | None = None,
           error: str | None = None, condition: str | None = None, team: list[str] | None = None,
           objections: list[dict] | None = None) -> str:
    """`team` holds one line per analyst request (condition C): who was asked what, and how it went.
    `objections` are the critic's, each with its outcome (condition D)."""
    number = {record_id: n for n, record_id in enumerate(report.sources, start=1)}
    lines = [f"# {question}", "", f"- Run status: {RUN_STATUS.get(status, status)}", f"- Cutoff: {cutoff}"]
    lines += [f"- Condition: {condition}"] if condition else []
    lines += [f"- Model: {model}"] if model else []
    lines += [f"- Run: {run_id}"] if run_id else []
    lines += [f"- Error: {error}"] if error else []
    if plan:
        lines += ["", "## Plan", "", plan.strip()]
    if team:
        lines += ["", "## Who did what", ""] + [f"- {line}" for line in team]
    for key, heading in SECTIONS:
        lines += ["", f"## {heading} ({report.section_status(key)})", ""]
        claims = report.sections[key]
        lines += [f"- {c.text}{''.join(f' [{number[i]}]' for i in c.citations)}"
                  + (" (qualified: see checker flags)" if c.flags else "") for c in claims] or ["- Nothing to report."]
    if objections:
        lines += ["", "## Review", ""] + [review_line(o, number) for o in objections]
    if report.limitations:
        lines += ["", "## Limitations", ""] + [f"- {text}" for text in report.limitations]
    if report.flags:
        lines += ["", "## Flags", ""] + [f"- {flag.where}: {flag.problem}" for flag in report.flags]
    if report.sources:
        lines += ["", "## Sources", ""] + [f"{number[i]}. {describe(records[i]).rstrip()}" for i in report.sources]
    return "\n".join(lines) + "\n"


def review_line(o: dict, number: dict[str, int]) -> str:
    """One objection: what the critic said about which claim version, and how it ended (REFERENCE §3)."""
    def refs(ids):
        return "".join(f" [{number[i]}]" for i in ids if i in number)
    owner = o["owner"] + (" analyst" if o["owner"] != "coordinator" else "")
    line = (f"- `{o['id']}` on `{o['claim']}` v{o['version']} ({o['issue'].replace('_', ' ')}, "
            f"{'material' if o['material'] else 'minor'}, round {o['round']}, owner: {owner}): {o['problem']}"
            f"{refs(o['evidence'])} Requested check: {o['requested_check']}")
    outcome = o["outcome"] + (f" as v{o['new_version']}" if o.get("new_version") else "") + (
        f" by adding {', '.join(f'`{i}`' for i in o['new_claims'])}" if o.get("new_claims") else "")
    line += f"\n  - Outcome: {outcome}" + (f" in round {o['closed_in']}" if o.get("closed_in") else "")
    line += (f": {o['explanation']}{refs(o['citations'])}" if o.get("explanation") else "")
    return line + "".join(f"\n  - Note: {note}" for note in o["notes"])


def describe(record: dict) -> str:
    """One line saying where a cited record comes from."""
    kind, rid = record.get("kind"), record["id"]
    if kind == "fact" and not record.get("accession"):  # a value from another provider, e.g. get_macro's rates
        period = f"{record['start']} to {record['end']}" if record.get("start") else f"at {record['end']}"
        origin = " ".join(str(p) for p in (record.get("source"), record.get("series_id")) if p)
        vintage = f", as published on {record['vintage']}" if record.get("vintage") else ""
        return f"`{rid}` {record.get('metric')} = {format_value(record)}, {period} ({origin}{vintage}) {record.get('url', '')}"
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
    if kind == "peers":
        names = ", ".join(f"{p['name']} ({', '.join(p['tickers'])})" for p in record.get("peers") or []) or "none"
        etf = (record.get("sector") or {}).get("ticker") or "none"
        return f"`{rid}` Peers of {record.get('name')}: {names}. Sector ETF {etf}. {record.get('method')} {record.get('url', '')}"
    if kind == "insider":
        plan = ", under a 10b5-1 plan" if record.get("plan_10b5_1") else ""
        return (f"`{rid}` {record.get('owner')} ({record.get('role')}): {record.get('meaning')} of {record.get('shares')} "
                f"shares at {record.get('price')} on {record.get('date')}{plan} (Form {record.get('form')} "
                f"{record.get('accession')}, filed {record.get('filed')}) {record.get('url', '')}")
    if kind == "calendar":
        dates = "; ".join(f"{r['date']} {r['name']}" for r in record.get("releases") or []) or "none"
        return f"`{rid}` Release dates {record.get('start')} to {record.get('end')} ({record.get('source')}): {dates} {record.get('url', '')}"
    if kind == "check":
        return f"`{rid}` {record.get('fact_id')} checked against the filing: {record.get('verdict')} {record.get('filing_url', '')}"
    if kind == "claim":
        cites = ", ".join(f"`{i}`" for i in record.get("citations") or []) or "nothing"
        return f"`{rid}` {record.get('author')} analyst finding (v{record.get('version')}): {record.get('text')} Cites {cites}."
    return f"`{rid}` {kind} record"
