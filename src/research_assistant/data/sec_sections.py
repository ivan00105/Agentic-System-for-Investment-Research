"""Filing sections (Item 1A, Item 7, ...) parsed by edgartools from bytes we fetched ourselves.

edgartools passed the gate on 12 hand-checked filings (REFERENCE §10), with one known issue: filers that
put MD&A inside a cross-referenced "Financial Section" (JPM, XOM) can run into Item 8. That case is
flagged, not hidden. Parsing a large filing takes up to ~20 s, so parsed sections are cached for good.
"""
import json
import re
from datetime import datetime, timezone

from .. import config
from .cache import DiskCache
from .errors import DataError
from .sec import SecClient
from .sec_filings import Filing

AUDITOR_REPORT = re.compile(r"Report of Independent Registered Public Accounting Firm", re.IGNORECASE)


def decode(raw: bytes) -> tuple[str, list[str]]:
    try:
        return raw.decode("utf-8-sig"), []
    except UnicodeDecodeError:
        # Older filings are often Windows-1252. Never silently: say so.
        return raw.decode("cp1252", errors="replace"), ["The filing is not UTF-8; it was read as Windows-1252."]


def sections(sec: SecClient, filing: Filing, cache: DiskCache) -> dict[str, dict]:
    """Every section edgartools found, by name (e.g. part_i_item_1a), with its text and detection details."""
    key = f"sections|edgartools|{filing.url}"
    cached = cache.get(key, None)  # filings never change
    if cached is not None:
        return json.loads(cached[0])
    html, notes = decode(sec.get(filing.url).body)
    from edgar.documents import ParserConfig, parse_html  # imported on first use: it pulls in pandas

    try:
        document = parse_html(html, ParserConfig(form=filing.form.removesuffix("/A")))
        found = {name: {"title": section.title, "item": section.item, "part": section.part,
                        "covered_items": list(section.covered_items), "method": section.detection_method,
                        "confidence": section.confidence, "warnings": [str(w) for w in section.warnings] + notes,
                        "text": section.text() or ""}
                 for name, section in document.sections.items()}
    except Exception as exc:  # edgartools raises many types; any of them means "can't split this filing"
        raise DataError(f"edgartools could not split {filing.url} into sections: {exc}", "bad_data") from exc
    cache.put(key, json.dumps(found).encode(), datetime.now(timezone.utc))
    return found


def find_item(found: dict[str, dict], item: str, part: str | None) -> list[str]:
    """Section names for an item like "1A" or "7", optionally within a part ("I", "II"); several means ambiguous."""
    wanted = re.sub(r"^item[\s._]*", "", item.strip().lower()).rstrip(".")
    names = [name for name, section in found.items()
             if name.endswith(f"item_{wanted}") or wanted in [c.lower() for c in section["covered_items"]]]
    if part:
        names = [name for name in names if name.startswith(f"part_{part.strip().lower()}_")]
    return names


def chunks(text: str) -> list[str]:
    """Paragraphs, with headings (short lines) joined to the paragraph that follows them.

    Some filings (e.g. TSM's 20-F) put a blank line after every wrapped line, so short pieces also
    close a paragraph at a sentence end once it is paragraph-sized. A paragraph is never cut.
    """
    pieces = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    merged: list[str] = []
    pending = ""
    for piece in pieces:
        short = len(piece) < config.SECTION_HEADING_MAX_CHARS
        pending = (f"{pending}\n{piece}" if short else f"{pending}\n\n{piece}") if pending else piece
        if not short or (len(pending) >= config.SECTION_HEADING_MAX_CHARS and piece.endswith((".", ":", ";", "?", "!"))):
            merged.append(pending)
            pending = ""
    if pending:
        merged.append(pending)
    return merged


def overrun_warning(name: str, text: str) -> str | None:
    if name.endswith(("item_7", "item_5")) and AUDITOR_REPORT.search(text):
        return ("This section contains an auditor's report, so it probably runs into Item 8 (financial "
                "statements); treat its last part with care.")
    return None
