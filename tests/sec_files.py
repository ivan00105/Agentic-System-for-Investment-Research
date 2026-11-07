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


class NoWait:
    def wait(self):
        pass


def make_context(tmp_path, cutoff: datetime = CUTOFF, files: SecFiles | None = None) -> ToolContext:
    sec = SecClient("Fieldnote test@example.com", tmp_path / "sec", transport=httpx.MockTransport(files or SecFiles()),
                    limiter=NoWait(), sleep=lambda s: None)
    return ToolContext(cutoff=cutoff, sec=sec, cache_dir=tmp_path / "cache")
