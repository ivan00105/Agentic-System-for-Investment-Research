"""An append-only JSONL trace of one agent run: every model call, tool call, result and token count."""
import json
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable
from uuid import uuid4

from .. import config

USAGE_FIELDS = ("prompt_tokens", "completion_tokens", "total_tokens")


def _zero() -> dict:
    # cached_tokens and cost stay None unless the provider reports them (OpenRouter does in `usage`).
    return {"model_calls": 0, "tool_calls": 0, **dict.fromkeys(USAGE_FIELDS, 0), "cached_tokens": None, "cost": None}


class Trace:
    """Each event is written and closed at once, so a crash or a cancelled run still leaves its trace.

    Events hold the model's visible text and tool calls, never its hidden reasoning (REFERENCE §2)."""

    def __init__(self, path: Path, run_id: str, echo: Callable[[dict], None] | None = None):
        self.path, self.run_id, self.echo = Path(path), run_id, echo
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.seq = 0
        self.totals = _zero()
        # Hosts that served the model calls (OpenRouter may fall back between them), so a fallback is never silent.
        self.hosts: list[str] = []
        self.frozen: dict[str, dict] = {}  # records already saved in this trace, by ID
        self.agent: str | None = None  # the role writing events now (see acting_as)
        self.by_agent: dict[str, dict] = {}  # totals per role

    @classmethod
    def new(cls, folder: Path | None = None, echo: Callable[[dict], None] | None = None) -> "Trace":
        run_id = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S-") + uuid4().hex[:6]
        return cls((folder or config.trace_dir()) / f"{run_id}.jsonl", run_id, echo)

    @contextmanager
    def acting_as(self, agent: str):
        """Tag every event written inside with the role that wrote it, so the trace shows who did what.
        Nests: an analyst asked by the coordinator tags its own events, then the coordinator's resume."""
        outer, self.agent = self.agent, agent
        try:
            yield
        finally:
            self.agent = outer

    def write(self, kind: str, **fields) -> dict:
        """Append one event. An event with `usage` is a model call and counts toward the totals."""
        self.seq += 1
        event = {"seq": self.seq, "at": datetime.now(timezone.utc).isoformat(), "kind": kind,
                 **({"agent": self.agent} if self.agent else {}), **fields}
        if "usage" in fields:
            self._count(fields["usage"] or {})
            if fields.get("provider") and fields["provider"] not in self.hosts:
                self.hosts.append(fields["provider"])
        if kind == "tool_call":
            for totals in self._tallies():
                totals["tool_calls"] += 1
        with self.path.open("a", encoding="utf-8") as file:
            file.write(json.dumps(event, default=str, ensure_ascii=False) + "\n")
        if self.echo:
            self.echo(event)
        return event

    def new_records(self, records: dict[str, dict]) -> dict[str, dict]:
        """The records not yet saved in this trace (or changed since), marked as saved. Each tool call writes
        these in full, so the trace freezes the run's evidence once (evidence.py reads it back)."""
        new = {key: record for key, record in records.items() if self.frozen.get(key) != record}
        self.frozen.update(new)
        return new

    def _tallies(self) -> list[dict]:
        return [self.totals] + ([self.by_agent.setdefault(self.agent, _zero())] if self.agent else [])

    def _count(self, usage: dict):
        for totals in self._tallies():
            totals["model_calls"] += 1
            for name in USAGE_FIELDS:
                if isinstance(usage.get(name), int):
                    totals[name] += usage[name]
            # Prompt tokens the host served from its prompt cache, billed at a fraction of the input price.
            cached = (usage.get("prompt_tokens_details") or {}).get("cached_tokens")
            if isinstance(cached, int):
                totals["cached_tokens"] = (totals["cached_tokens"] or 0) + cached
            if isinstance(usage.get("cost"), (int, float)):
                totals["cost"] = round((totals["cost"] or 0) + usage["cost"], 8)
