"""Webapp-persisted model preferences (default source and per-agent overrides), stored without secrets."""
import json
import os
from dataclasses import replace
from pathlib import Path

from .contracts import DomainError
from .model_access import (BUILTIN_PROVIDERS, ModelSettings, load_model_settings, load_model_sources,
                           resolve_model_source)

PREFS_FILE = "model_preferences.json"
ALLOWED_ROLES = ("coordinator", "fundamentals", "filings", "market", "critic", "single_agent", "screener")


def load_model_preferences(data_dir: Path | None) -> dict:
    """Saved {default_source, agent_models}; missing or corrupt files degrade cleanly."""
    empty = {"default_source": None, "agent_models": {}}
    if data_dir is None:
        return empty
    path = Path(data_dir) / PREFS_FILE
    if not path.is_file():
        return empty
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return empty
    if not isinstance(raw, dict):
        return empty
    default_source = raw.get("default_source")
    default_source = default_source.strip() if isinstance(default_source, str) and default_source.strip() else None
    routes = {}
    if isinstance(raw.get("agent_models"), dict):
        for role, source_id in raw["agent_models"].items():
            if role in ALLOWED_ROLES and isinstance(source_id, str) and source_id.strip():
                routes[role] = source_id.strip()
    return {"default_source": default_source, "agent_models": routes}


def _canonical_source(source_id: str, sources: dict) -> str:
    """Map a built-in provider ID that is also the .env primary source to 'default' so UI dropdowns match."""
    if source_id in sources:
        return source_id
    if source_id in BUILTIN_PROVIDERS:
        primary = load_model_settings()
        candidate = resolve_model_source(source_id)
        if (candidate.configured and primary.configured
                and candidate.provider == primary.provider
                and candidate.model == primary.model
                and candidate.base_url == primary.base_url
                and candidate.api_key == primary.api_key):
            return "default"
    return source_id


def save_model_preferences(data_dir: Path, default_source: str | None = None,
                           agent_models: dict[str, str] | None = None) -> dict:
    """Validate against configured sources and persist atomically in data_dir."""
    sources = {source.id: source for source in load_model_sources()}
    current = load_model_preferences(data_dir)
    next_default = current["default_source"]
    if default_source is not None:
        cleaned = _canonical_source(default_source.strip(), sources)
        if not cleaned or cleaned == "default":
            next_default = None
        else:
            if cleaned not in sources:
                raise DomainError(f"Unknown model source: {cleaned}.", "bad_model_source", 422)
            if not sources[cleaned].configured:
                raise DomainError(f"Model source {cleaned} is not configured.", "model_source_not_configured", 409)
            next_default = cleaned
    next_routes = dict(current["agent_models"])
    if agent_models is not None:
        if unknown := set(agent_models) - set(ALLOWED_ROLES):
            raise DomainError(f"Unknown agent role: {', '.join(sorted(unknown))}.", "bad_agent_model", 422)
        for role, source_id in agent_models.items():
            cleaned = _canonical_source((source_id or "").strip(), sources)
            if not cleaned:
                next_routes.pop(role, None)
                continue
            if cleaned not in sources:
                raise DomainError(f"Unknown model source: {cleaned}.", "bad_model_source", 422)
            if not sources[cleaned].configured:
                raise DomainError(f"The model source for {role} is not configured.", "model_source_not_configured", 409)
            next_routes[role] = cleaned
    payload = {"default_source": next_default, "agent_models": next_routes}
    Path(data_dir).mkdir(parents=True, exist_ok=True)
    tmp = Path(data_dir) / f"{PREFS_FILE}.tmp"
    tmp.write_text(json.dumps(payload, indent=1, sort_keys=True), encoding="utf-8")
    os.replace(tmp, Path(data_dir) / PREFS_FILE)
    return payload


def active_preferences(data_dir: Path | None) -> dict:
    """Saved preferences filtered to sources currently configured in the environment."""
    prefs = load_model_preferences(data_dir)
    sources = {source.id: source for source in load_model_sources()}
    default_source = prefs["default_source"]
    if default_source not in sources or not sources[default_source].configured:
        default_source = None
    routes = {role: sid for role, sid in prefs["agent_models"].items() if sid in sources and sources[sid].configured}
    return {"default_source": default_source, "agent_models": routes}


def effective_model_settings(data_dir: Path | None, *, default_source: str | None = None,
                             model: str | None = None, agent_models: dict[str, str] | None = None) -> ModelSettings:
    """Resolve active default ModelSettings and per-role routes from saved prefs plus per-run overrides."""
    prefs = active_preferences(data_dir)
    sources = {source.id: source for source in load_model_sources()}
    chosen_default = _canonical_source(raw_default, sources) if (raw_default := (default_source or prefs["default_source"])) else None
    if chosen_default:
        if chosen_default not in sources:
            raise DomainError(f"Unknown model source: {chosen_default}.", "bad_model_source", 422)
        base = resolve_model_source(chosen_default)
        if not base.configured:
            raise DomainError(base.error or f"Model source {chosen_default} is not configured.",
                              "model_source_not_configured", 409)
    else:
        base = load_model_settings()
    if model:
        base = replace(base, model=model)
    merged = dict(prefs["agent_models"])
    if agent_models is not None:
        if unknown := set(agent_models) - set(ALLOWED_ROLES):
            raise DomainError(f"Unknown agent role: {', '.join(sorted(unknown))}.", "bad_agent_model", 422)
        for role, source_id in agent_models.items():
            cleaned = _canonical_source((source_id or "").strip(), sources)
            if not cleaned:
                merged.pop(role, None)
            elif cleaned not in sources:
                raise DomainError(f"Unknown model source: {cleaned}.", "bad_model_source", 422)
            else:
                merged[role] = cleaned
    if merged:
        base = base.with_routes(merged)
        for role in merged:
            if not base.for_role(role).configured:
                raise DomainError(f"The model source for {role} is not configured.", "model_source_not_configured", 409)
    return base

