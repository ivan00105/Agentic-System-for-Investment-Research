"""What every tool returns, and the host-owned context every tool runs in."""
import hashlib
import threading
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Literal

from pydantic import BaseModel

from .. import config
from ..data.cache import DiskCache
from ..data.sec import SecClient

# ok: everything asked for is here. partial: some of it; each missing piece says why.
# unsupported: this kind of company or filing isn't handled (IFRS filers, a bank's operating income).
# not_found: it doesn't exist (unknown company, no such filing). unavailable: it couldn't be fetched
# now (provider not configured or down). invalid: the arguments were wrong.
Status = Literal["ok", "partial", "unsupported", "not_found", "unavailable", "invalid"]


class ToolResult(BaseModel):
    status: Status
    data: Any = None
    ids: list[str] = []  # citable record IDs in `data`, e.g. fact-..., calc-..., chunk-...
    source: str  # who provided the data, e.g. "SEC companyfacts" or "yfinance (fallback)"
    warnings: list[str] = []


@dataclass
class ToolContext:
    """Trusted state owned by the host, never by model arguments (REFERENCE §8)."""

    cutoff: datetime
    sec: SecClient
    # Every citable record returned so far in this run, by ID. calculate and the checker resolve IDs here.
    records: dict[str, dict] = field(default_factory=dict)
    # Price providers to try, best first; None means config order. The evaluation pins this list.
    price_providers: list[str] | None = None
    cache_dir: Path | None = None  # None means config.data_dir()
    # Set by the host to cancel the run (the web app's cancel button); agent loops check it before each step.
    stop: threading.Event = field(default_factory=threading.Event)

    def cache(self, name: str) -> DiskCache:
        return DiskCache((self.cache_dir or config.data_dir()) / name)

    def remember(self, record: dict) -> str:
        self.records[record["id"]] = record
        return record["id"]


def make_id(prefix: str, *parts: object) -> str:
    """A short stable ID: the same inputs always give the same ID."""
    return f"{prefix}-" + hashlib.sha256("|".join(str(p) for p in parts).encode()).hexdigest()[:12]


@dataclass(frozen=True)
class Tool:
    name: str
    description: str  # what the model reads when choosing a tool
    input_model: type[BaseModel]
    run: Callable[[Any, ToolContext], ToolResult]
    source: str  # label used when the tool fails before choosing a provider

    def schema(self) -> dict:
        """The Chat Completions function schema."""
        return {"type": "function", "function": {
            "name": self.name, "description": self.description, "parameters": self.input_model.model_json_schema()}}
