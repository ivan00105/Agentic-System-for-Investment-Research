"""Saved agent runs, read back from their trace files (PROJECT_GUIDE Phase 7: the files in data/traces/ are the
store, no database): a summary per run for History, a run's progress lines, and its checked report."""
import json
import os
import re
from pathlib import Path

from . import preferences
from .checker import PLACEHOLDER, lookup
from .draft import SECTIONS
from .evidence import load
from .figures import figures, raw
from .objections import ISSUES
from .progress import describe as progress_line
from .report import RUN_STATUS, describe
from .sources import GROUPS, chip, detail

RUN_ID = re.compile(r"\d{8}-\d{6}-[0-9a-f]{6}")  # the IDs Trace.new gives; any other file is not a run


def runs(folder: Path) -> list[dict]:
    """Every saved run, newest first (run IDs start with the time)."""
    paths = sorted(folder.glob("*.jsonl"), reverse=True) if folder.is_dir() else []
    return [found for path in paths if RUN_ID.fullmatch(path.stem) and (found := summary(path))]


def summary(path: Path) -> dict | None:
    """What History shows. `status` is None while the trace has no run_end: still running, or cut off by a crash."""
    first, last = _ends(path)
    if first is None:
        return None
    end = last if last and last.get("kind") == "run_end" else {}
    question, note = preferences.split(first.get("question"))
    return {"run_id": path.stem, "question": question, "preferences": note, "condition": first.get("condition"),
            "cutoff": first.get("cutoff"), "model": first.get("model"), "started_at": first.get("at"),
            "status": end.get("status"), "ended_at": end.get("at"), "totals": end.get("totals")}


def progress(path: Path) -> list[dict]:
    """One line per step worth showing, the same lines the CLI prints, with the role that took it (the CLI's
    "[role] " prefix) and the event kind, so the page can group the lines by role."""
    lines = []
    for event in read_events(path):
        try:
            text = progress_line(event)
        except (KeyError, TypeError):  # traces from before a field was added
            text = event.get("kind")
        if text:
            role = event.get("agent")
            lines.append({"seq": event.get("seq"), "at": event.get("at"), "kind": event.get("kind"), "role": role,
                          "text": text.removeprefix(f"[{role}] ") if role else text})
    return lines


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
    """A Discover run's shortlist: the spec as shown, the counts, and each checked candidate with its check's
    lines and, for a researched one, its own run and that report's answer."""
    spec = next((e for e in reversed(run.events) if e["kind"] == "screen_spec"), None)
    checks = {e["rank"]: e for e in run.events if e["kind"] == "candidate"}
    candidates = [{key: c.get(key) for key in ("rank", "cik", "name", "outcome", "verdict", "run_id")}
                  | {"lines": (checks.get(c["rank"]) or {}).get("lines", []), "answer": _answer(folder, c.get("run_id"))}
                  for c in run.end["candidates"]]
    return {"spec": spec and spec["shown"], "counts": run.end.get("counts") or {}, "candidates": candidates}


def _answer(folder: Path, run_id: str | None) -> str | None:
    """The first summary statement of a pick's own report: its answer."""
    path = folder / f"{run_id}.jsonl" if run_id and RUN_ID.fullmatch(run_id) else None
    if path is None or not path.is_file():
        return None
    claims = ((_ends(path)[1] or {}).get("report") or {}).get("sections", {}).get("summary") or []
    return claims[0]["text"] if claims else None


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
