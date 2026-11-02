"""Every data provider by kind, with its tier and settings, for the status page (REFERENCE §10).

Tiers: 0 = free, no key; 1 = free with a key; 2 = paid. A provider without its settings is skipped
and shown as "not configured" with the variable to set; nothing crashes.
"""
import os
import tempfile
from dataclasses import dataclass
from typing import Callable

from ..model_access import load_model_settings
from . import prices, prices_tiingo, prices_yfinance
from .sec import SecClient


@dataclass(frozen=True)
class Provider:
    name: str
    kind: str
    label: str
    tier: int
    env: tuple[str, ...]  # settings it needs in .env
    configured: Callable[[], bool]
    check: Callable[[], str] | None = None  # a live request; returns a message or raises


def _sec_configured() -> bool:
    return SecClient().configured


def _sec_check() -> str:
    # A throwaway cache so the check really reaches SEC.
    with tempfile.TemporaryDirectory() as folder, SecClient(cache_dir=folder) as sec:
        if not sec.configured:
            raise RuntimeError("SEC_USER_AGENT is not set to a name and contact email.")
        sec.submissions(320193)
    return "SEC answered with the User-Agent from SEC_USER_AGENT."


def _model_env() -> tuple[str, ...]:
    settings = load_model_settings()
    keys = {"openrouter": "OPENROUTER_API_KEY", "openai": "OPENAI_API_KEY", "compatible": "OPENAI_API_KEY"}
    return ("RESEARCH_MODEL", keys[settings.provider]) + (("OPENAI_BASE_URL",) if settings.provider == "compatible" else ())


def all_providers() -> list[Provider]:
    sec = dict(tier=0, env=("SEC_USER_AGENT",), configured=_sec_configured, check=_sec_check)
    price_adapters = [prices.ADAPTERS[name] for name in prices.provider_order()]
    price_adapters += [a for a in (prices_tiingo, prices_yfinance) if a not in price_adapters]
    settings = load_model_settings()
    return [
        Provider("sec_companyfacts", "fundamentals", "SEC companyfacts", **sec),
        Provider("sec_archives", "filings", "SEC EDGAR filings", **sec),
        Provider("sec_tickers", "identity", "SEC company tickers", **sec),
        *[Provider(a.NAME, "prices", a.LABEL, a.TIER, a.ENV, a.configured, a.check) for a in price_adapters],
        Provider("model", "llm", settings.label, 2, _model_env(), lambda: load_model_settings().configured),
    ]


def status(checks: dict[str, dict]) -> list[dict]:
    """One entry per kind: its providers in priority order and which one is active."""
    kinds: dict[str, dict] = {}
    for provider in all_providers():
        last = checks.get(provider.name)
        configured = provider.configured()
        if last and not last["ok"]:
            state = "check_failed"
        elif not configured:
            state = "not_configured"
        else:
            state = "ready" if not provider.env else "configured"
        missing = [name for name in provider.env if not os.getenv(name, "").strip()]
        kind = kinds.setdefault(provider.kind, {"kind": provider.kind, "active": None, "providers": []})
        if configured and kind["active"] is None:
            kind["active"] = provider.name
        kind["providers"].append({"name": provider.name, "label": provider.label, "tier": provider.tier,
                                  "env": list(provider.env), "missing_env": missing if not configured else [],
                                  "status": state, "last_check": last, "can_check": provider.check is not None})
    return list(kinds.values())


def run_check(name: str) -> dict:
    provider = next((p for p in all_providers() if p.name == name), None)
    if provider is None or provider.check is None:
        raise KeyError(name)
    try:
        return {"ok": True, "message": provider.check()}
    except Exception as exc:  # a check reports any failure; it never crashes the status page
        return {"ok": False, "message": f"{type(exc).__name__}: {exc}"}
