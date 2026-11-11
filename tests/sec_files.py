"""Serve the trimmed real SEC files in tests/fixtures/sec/ through a mocked transport (no network)."""
from datetime import datetime, timezone
from pathlib import Path

import httpx

from research_assistant.data.sec import SecClient
from research_assistant.tools.result import ToolContext

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "sec"
TICKER_BY_CIK = {"0000320193": "AAPL", "0000019617": "JPM", "0001046179": "TSM", "0001577552": "BABA",
                 "0001015922": "CHKP"}
# Late enough that every fixture filing is public.
CUTOFF = datetime(2026, 11, 1, tzinfo=timezone.utc)
# Real rows from Airbnb's IPO (form, filing date, acceptance time, accession). SEC released the drafts and the
# review letters only after the S-1, but dates them by submission (REFERENCE §5).
ABNB_SUBMISSIONS = "/submissions/CIK0001559720.json"
ABNB_IPO = [
    ("S-1/A", "2020-12-01", "2020-12-01T12:24:52.000Z", "0001193125-20-306257"),
    ("CORRESP", "2020-11-16", "2020-11-16T21:25:52.000Z", "0001193125-20-294804"),
    ("S-1", "2020-11-16", "2020-11-16T21:23:52.000Z", "0001193125-20-294801"),
    ("DRSLTR", "2020-09-30", "2020-09-30T21:10:30.000Z", "0000950123-20-010023"),
    ("DRS/A", "2020-09-30", "2020-09-30T21:07:28.000Z", "0000950123-20-010021"),
    ("UPLOAD", "2020-09-17", "2020-09-17T19:35:23.000Z", "0000000000-20-008766"),
    ("DRS", "2020-08-19", "2020-08-19T20:18:11.000Z", "0000950123-20-009252"),
]


def fixture_name(path: str) -> str | None:
    name = path.rsplit("/", 1)[-1]
    if path.startswith("/api/xbrl/companyfacts/") or path.startswith("/submissions/CIK") and "-submissions-" not in name:
        ticker = TICKER_BY_CIK.get(name.removeprefix("CIK").removesuffix(".json"))
        kind = "companyfacts" if "companyfacts" in path else "submissions"
        return ticker and f"{kind}_{ticker}.json"
    if path.startswith("/api/xbrl/frames/"):
        _, _, _, _, _, tag, _, period = path.split("/")
        return f"frame_{tag}_{period}"
    return name


class SecFiles:
    """A mocked SEC: answers from fixtures (404 otherwise) and records every requested path."""

    def __init__(self, overrides: dict[str, httpx.Response] | None = None):
        self.paths: list[str] = []
        self.overrides = overrides or {}

    def __call__(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        self.paths.append(path)
        if path in self.overrides:
            return self.overrides[path]
        name = fixture_name(path)
        file = FIXTURES / name if name else None
        return httpx.Response(200, content=file.read_bytes()) if file and file.is_file() else httpx.Response(404)


def submissions(rows: list[tuple[str, str, str, str]]) -> httpx.Response:
    """A submissions JSON holding only these (form, filed, accepted, accession) rows."""
    form, filed, accepted, accession = (list(column) for column in zip(*rows, strict=True))
    recent = {"accessionNumber": accession, "form": form, "filingDate": filed, "acceptanceDateTime": accepted,
              "primaryDocument": ["filename1.htm"] * len(rows)}
    return httpx.Response(200, json={"filings": {"recent": recent, "files": []}})


class NoWait:
    def wait(self):
        pass


def make_context(tmp_path, cutoff: datetime = CUTOFF, files: SecFiles | None = None) -> ToolContext:
    sec = SecClient("Fieldnote test@example.com", tmp_path / "sec", transport=httpx.MockTransport(files or SecFiles()),
                    limiter=NoWait(), sleep=lambda s: None)
    return ToolContext(cutoff=cutoff, sec=sec, cache_dir=tmp_path / "cache")
