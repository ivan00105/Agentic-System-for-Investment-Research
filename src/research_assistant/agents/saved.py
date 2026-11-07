"""Saved agent runs, read back from their trace files (PROJECT_GUIDE Phase 7: the files in data/traces/ are the
store, no database): a summary per run for History, a run's progress lines, and its checked report. Traces are
frozen evidence, so the user's labels and archived flags live apart, in labels.json in the same folder."""
import json
import os
import re
from pathlib import Path

from . import preferences
from .checker import PLACEHOLDER, lookup
from .discover import pick_title
from .draft import SECTIONS
from .evidence import load
from .figures import figures, raw
from .objections import ISSUES
from .progress import timeline
from .report import RUN_STATUS, describe
from .sources import GROUPS, chip, detail

RUN_ID = re.compile(r"\d{8}-\d{6}-[0-9a-f]{6}")  # the IDs Trace.new gives; any other file is not a run
LABELS = "labels.json"


def runs(folder: Path, archived: bool = False) -> list[dict]:
    """The top-level runs, newest first (run IDs start with the time), each with the runs it started under
    `children`, oldest first. Archived runs are listed apart; a child goes wherever its parent is."""
    return [run for run in tree(folder) if run["archived"] == archived]


def tree(folder: Path) -> list[dict]:
    """Every saved run, nested under the run that started it (see _parents)."""
    paths = sorted(folder.glob("*.jsonl"), reverse=True) if folder.is_dir() else []
    marks, found, started = labels(folder), {}, {}
    for path in paths:
        if RUN_ID.fullmatch(path.stem) and (read := _summary(path, marks.get(path.stem))):
            found[path.stem], started[path.stem] = read
    parents = _parents(found, started)
    roots = {run_id: _root(run_id, parents) for run_id in found}
    top = {run_id: run | {"children": []} for run_id, run in found.items() if roots[run_id] == run_id}
    for run_id in sorted(parents):  # oldest first: pick 1, pick 2, ...
        child = found[run_id]  # a child that isn't a pick came from "Compare these" on the shortlist
        top[roots[run_id]]["children"].append(child | {"kind": child["kind"] or "comparison"})
    return list(top.values())


def _root(run_id: str, parents: dict[str, str]) -> str:
    while run_id in parents:  # _parents never keeps a link that closes a loop, so this ends
        run_id = parents[run_id]
    return run_id


def summary(path: Path, mark: dict | None = None) -> dict | None:
    """What History shows. `status` is None while the trace has no run_end: still running, or cut off by a crash.
    `mark` is the run's entry in labels.json."""
    read = _summary(path, mark)
    return read and read[0]


def _summary(path: Path, mark: dict | None) -> tuple[dict, list[str]] | None:
    """The summary, and the runs a Discover run_end lists as its research runs."""
    first, last = _ends(path)
    if first is None:
        return None
    end, mark = last if last and last.get("kind") == "run_end" else {}, mark or {}
    question, note = preferences.split(first.get("question"))
    pick = pick_title(question)
    # The title: the user's label, a pick's company, else the question. Lists clamp it; the run page shows it all.
    return ({"run_id": path.stem, "title": mark.get("label") or pick or question, "label": mark.get("label"),
             "question": question, "preferences": note, "kind": "pick" if pick else None,
             "parent_run_id": first.get("parent_run_id"), "archived": bool(mark.get("archived")),
             "condition": first.get("condition"), "cutoff": first.get("cutoff"), "model": first.get("model"),
             "started_at": first.get("at"), "status": end.get("status"), "ended_at": end.get("at"),
             "totals": end.get("totals")},
            [c["run_id"] for c in end.get("candidates") or [] if isinstance(c, dict) and c.get("run_id")])


def _parents(found: dict[str, dict], started: dict[str, list[str]]) -> dict[str, str]:
    """Each run's parent: the run_start's parent_run_id, or for traces saved before it was written, the Discover
    run whose run_end lists it. Only a saved run started no later than its child counts (the ID's time part, since
    runs in the same second have random suffixes), and a link that would close a loop is dropped."""
    links = {child: run_id for run_id, children in started.items() for child in children}
    links |= {run_id: run["parent_run_id"] for run_id, run in found.items() if run["parent_run_id"]}
    parents = {}
    for child, parent in sorted(links.items()):
        if (child in found and parent in found and parent != child and parent[:15] <= child[:15]
                and _root(parent, parents) != child):
            parents[child] = parent
    return parents


def labels(folder: Path) -> dict[str, dict]:
    """labels.json: run ID -> {"label": ..., "archived": true}. Unreadable reads as none, so History still lists."""
    try:
        return _marks(folder)
    except ValueError:
        return {}


def _marks(folder: Path) -> dict[str, dict]:
    path = folder / LABELS
    found = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
    if not isinstance(found, dict):
        raise ValueError(f"{path} is not a JSON object")
    return found


def progress(path: Path) -> list[dict]:
    """The run's timeline: one entry per model step (its tool calls folded under it) or other event worth a line,
    with the role that wrote it and the event kind, so the page can group the entries by role."""
    return timeline(read_events(path))


def read_events(path: Path) -> list[dict]:
    """Every event written so far. A run still writing can leave half a line at the end; it is skipped."""
    events = []
    for line in path.read_bytes().splitlines():
        if (event := _parse(line)) is not None:
            events.append(event)
    return events


def report(path: Path) -> dict | None:
    """A finished run's checked report, shaped for the page; None while the trace has no run_end."""
    run = load(path)
    if run.end is None:
        return None
    end, checked = run.end, run.end.get("report") or {}  # Discover's run_end has only Markdown
    number = {record_id: n for n, record_id in enumerate(checked.get("sources", []), start=1)}
    sections = []
    for key, heading in (SECTIONS if checked else ()):
        claims = [{"text": c["text"], "status": "qualified" if c["flags"] else "cited",
                   "citations": [number[i] for i in c["citations"] if i in number],
                   "flags": [flag["problem"] for flag in c["flags"]]} for c in checked["sections"].get(key, [])]
        status = "abstained" if not claims else "qualified" if any(c["flags"] for c in claims) else "cited"
        sections.append({"key": key, "heading": heading, "status": status, "claims": claims})
    return {"status": end["status"], "status_label": RUN_STATUS.get(end["status"], end["status"]),
            "error": end.get("error"), "sections": sections, "limitations": checked.get("limitations", []),
            "flags": [f"{flag['where']}: {flag['problem']}" for flag in checked.get("flags", [])],
            "objections": [_objection(o) for o in end.get("objections") or []],
            "sources": [_source(n, i, run.records) for i, n in number.items()],
            "figures": figures(checked["sources"], _shown(end, run.records), run.records) if checked else None,
            "raw": raw(checked["sources"], run.records) if checked else [],
            "discover": _discover(run, path.parent) if "candidates" in end else None,
            "markdown": end.get("markdown") or ""}


def questions(path: Path) -> dict | None:
    """What a Discover run waiting for the user asks: its draft spec as shown, and each vague term's question."""
    found = next((e for e in reversed(read_events(path)) if e.get("kind") == "questions"), None)
    return found and {"terms": found["terms"], "shown": found["shown"], "spec": found.get("spec")}


def _discover(run, folder: Path) -> dict:
    """A Discover run's shortlist: the spec as shown, the counts, why the search ended, and each checked candidate
    with its check's lines and, for a researched one, its own run with that report's answer, flags and status."""
    spec = next((e for e in reversed(run.events) if e["kind"] == "screen_spec"), None)
    checks = {e["rank"]: e for e in run.events if e["kind"] == "candidate"}
    ends = {e["rank"]: e for e in run.events if e["kind"] == "research_end"}
    screens = [r for r in run.records.values() if r.get("kind") == "screen"]  # its rows hold each company's tickers
    tickers = {row["cik"]: row.get("tickers") or [] for r in screens for row in r.get("rows", [])}
    candidates = [{key: c.get(key) for key in ("rank", "cik", "name", "outcome", "verdict", "run_id")}
                  | {"tickers": tickers.get(c["cik"], []), "lines": (checks.get(c["rank"]) or {}).get("lines", [])}
                  | _answer(folder, c.get("run_id"), ends.get(c["rank"]))
                  for c in run.end["candidates"]]
    return {"spec": spec and spec["shown"], "counts": run.end.get("counts") or {}, "candidates": candidates,
            "notes": run.end.get("notes") or []}


def _answer(folder: Path, run_id: str | None, research_end: dict | None) -> dict:
    """A researched candidate's answer (the first summary statement of its own report) with that claim's
    citations, its run's status, and warnings: the claim's flags, the report's other flags and an unfinished run."""
    path = folder / f"{run_id}.jsonl" if run_id and RUN_ID.fullmatch(run_id) else None
    end = _ends(path)[1] if path and path.is_file() else None
    checked = (end or {}).get("report") or {}
    claim = next(iter(checked.get("sections", {}).get("summary") or []), None)
    status = (end or research_end or {}).get("status")
    warnings = [flag["problem"] for flag in claim["flags"]] if claim else []
    if (others := len(checked.get("flags") or []) - len(warnings)) > 0:
        warnings.append(f"Its report has {others} more flagged statement{'s' if others > 1 else ''}; open it to see them.")
    if research_end and research_end.get("error"):
        warnings.append(research_end["error"])
    if status and status != "finished":
        warnings.append(f"Its research run {RUN_STATUS.get(status, status)}.")
    return {"answer": claim and claim["text"], "citations": claim["citations"] if claim else [], "warnings": warnings,
            "run_status": status}


def record(path: Path, record_id: str) -> dict | None:
    """One frozen record as the evidence panel shows it, or None if the run holds no record with that ID."""
    records = load(path).records
    return detail(records[record_id], records) if record_id in records else None


def _shown(end: dict, records: dict[str, dict]) -> list[str]:
    """The records the key numbers were filled from, in order: the placeholders in the final draft. A claim also
    cites the inputs behind its figure, so its citations would list more than it shows."""
    if not end.get("draft"):  # traces saved before the draft was kept
        return [i for c in end["report"]["sections"]["key_numbers"] for i in c["citations"]]
    texts = [c if isinstance(c, str) else c.get("text", "") for c in end["draft"].get("key_numbers") or []]
    return [r["id"] for text in texts for m in PLACEHOLDER.finditer(text) if (r := lookup(records, m[2], m[1]))]


def _objection(o: dict) -> dict:
    """One critic objection; `meaning` says what its issue type means, `notes` why it ended as it did."""
    return {"claim": o["claim"], "version": o["version"], "where": o.get("where"),
            "issue": o["issue"].replace("_", " "), "meaning": ISSUES.get(o["issue"]), "material": o["material"],
            "problem": o["problem"], "outcome": o["outcome"], "explanation": o.get("explanation"),
            "notes": o.get("notes") or []}


def _source(n: int, record_id: str, records: dict[str, dict]) -> dict:
    """A numbered source with its chip label and the group it is listed under (facts, filing text, ...)."""
    if (record := records.get(record_id)) is None:  # traces saved before evidence was frozen hold no records
        return {"n": n, "id": record_id, "text": f"`{record_id}`", "url": None, "kind": None, "group": "Other",
                "label": record_id}
    text, url = describe(record).removeprefix(f"`{record_id}` "), record.get("filing_url") or record.get("url")
    return {"n": n, "id": record_id, "text": text.replace(url, "").strip() if url else text, "url": url,
            "kind": record.get("kind"), "group": GROUPS.get(record.get("kind"), "Other"), "label": chip(record, records)}


def _ends(path: Path) -> tuple[dict | None, dict | None]:
    """The first and last events, read from both ends: a long run's trace holds megabytes of evidence."""
    with path.open("rb") as file:
        first = file.readline()
        size, window = file.seek(0, os.SEEK_END), 1 << 16
        while True:  # widen the window until it holds the whole last line (a run_end can be hundreds of KB)
            start = max(0, size - window)
            file.seek(start)
            lines = file.read().rstrip().rsplit(b"\n", 1)
            if len(lines) == 2 or start == 0:
                return _parse(first), _parse(lines[-1])
            window *= 4


def _parse(line: bytes) -> dict | None:
    try:
        return json.loads(line)
    except ValueError:  # empty, or half-written by a run still going
        return None
