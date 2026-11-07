"""Every data provider by kind, with its tier and settings, for the Setup & status page (REFERENCE §10).

Tiers: 0 = free, no key; 1 = free with a key; 2 = paid. A provider without its settings is skipped
and shown as "not configured" with the variable to set; nothing crashes. The page learns only whether
a setting is set, never its value.
"""
import os
import tempfile
from dataclasses import dataclass
from typing import Callable

from ..contracts import DomainError
from ..model_access import check_model, load_model_settings
from . import fx, macro, prices, prices_tiingo, prices_yfinance
from .errors import DataError
from .sec import SecClient

# Each card's title and what its data is for, in page order.
KINDS = {
    "filings": ("SEC filings", "Lists a company's filings and reads sections of its 10-K, 10-Q and 8-K reports."),
    "fundamentals": ("Fundamentals", "Reported figures such as revenue, operating income and cash flow."),
    "identity": ("Company lookup", "Matches a company name or ticker to the company SEC knows."),
    "prices": ("Daily prices", "Closing prices for market cap, valuation ratios and risk."),
    "macro": ("Rates, inflation and release dates", "The risk-free rate for Sharpe ratios, Treasury yields, inflation "
              "and unemployment as context, and the dates of major US data releases."),
    "fx": ("Exchange rates", "Converts figures a foreign company reports in another currency (such as CNY or TWD) "
           "into US dollars: each year's average rate for income and cash flow, the year-end rate for balances."),
    "insiders": ("Insider trades", "Insiders' open-market purchases and sales from their SEC Form 4 filings."),
    "peers": ("Peers and sector", "Peers by SIC industry code and size, and the sector ETF to compare against (its "
              "prices come from the daily prices card)."),
    "llm": ("Model", "The language model that plans the research, calls the tools and writes the report."),
}


@dataclass(frozen=True)
class Provider:
    name: str
    kind: str
    label: str
    tier: int
    env: tuple[str, ...]  # settings it needs in .env
    configured: Callable[[], bool]
    check: Callable[[], str] | None = None  # a live request; returns a message or raises
    missing: Callable[[], list[str]] | None = None  # what to set when not configured; default: its unset env names
    problem: Callable[[], str | None] = lambda: None  # why settings that are set still don't work
    note: str = ""  # what this provider covers, when it isn't everything its card does


def _unset(names) -> list[str]:
    return [name for name in names if not os.getenv(name, "").strip()]


def _sec_configured() -> bool:
    return SecClient().configured


def _sec_problem() -> str | None:
    if os.getenv("SEC_USER_AGENT", "").strip() and not _sec_configured():
        return 'SEC_USER_AGENT needs a name and a contact email, e.g. "Fieldnote you@example.com".'
    return None


def _sec_check() -> str:
    # A throwaway cache so the check really reaches SEC.
    with tempfile.TemporaryDirectory() as folder, SecClient(cache_dir=folder) as sec:
        if not sec.configured:
            raise RuntimeError("SEC_USER_AGENT is not set to a name and contact email.")
        sec.submissions(320193)
    return "SEC answered with the User-Agent from SEC_USER_AGENT."


def _model_provider(name: str, label: str, tier: int, env: tuple[str, ...]) -> Provider:
    """One model service. Only the one RESEARCH_MODEL_PROVIDER selects (default: openai) can be active."""
    def selected() -> bool:
        return load_model_settings().provider == name

    def missing() -> list[str]:
        choose = [] if selected() else [f"RESEARCH_MODEL_PROVIDER={name}"]
        return choose + _unset(n for n in env if n != "RESEARCH_MODEL_PROVIDER")

    return Provider(name, "llm", label, tier, env, lambda: selected() and load_model_settings().configured,
                    check_model, missing, lambda: load_model_settings().error if selected() else None)


def all_providers() -> list[Provider]:
    sec = dict(tier=0, env=("SEC_USER_AGENT",), configured=_sec_configured, check=_sec_check, problem=_sec_problem)
    price_adapters = [prices.ADAPTERS[name] for name in prices.provider_order()]
    price_adapters += [a for a in (prices_tiingo, prices_yfinance) if a not in price_adapters]
    macro_adapters = [macro.ADAPTERS[name] for name in macro.provider_order()]
    macro_adapters += [a for a in macro.ADAPTERS.values() if a not in macro_adapters]
    fx_adapters = [fx.ADAPTERS[name] for name in fx.provider_order()]
    fx_adapters += [a for a in fx.ADAPTERS.values() if a not in fx_adapters]
    return [
        Provider("sec_archives", "filings", "SEC EDGAR filings", **sec),
        Provider("sec_companyfacts", "fundamentals", "SEC companyfacts", **sec),
        Provider("sec_tickers", "identity", "SEC company tickers", **sec),
        Provider("sec_form4", "insiders", "SEC Form 4 filings", **sec),
        Provider("sec_sic", "peers", "SEC company list by SIC code", **sec),
        *[Provider(a.NAME, "prices", a.LABEL, a.TIER, a.ENV, a.configured, a.check) for a in price_adapters],
        *[Provider(a.NAME, "macro", a.LABEL, a.TIER, a.ENV, a.configured, a.check, note=a.NOTE) for a in macro_adapters],
        # Names are unique across cards, so FRED's exchange rates are "fred_fx".
        *[Provider(f"{a.NAME}_fx" if a.NAME in macro.ADAPTERS else a.NAME, "fx", a.LABEL, a.TIER, a.ENV, a.configured,
                   a.check, note=a.NOTE) for a in fx_adapters],
        _model_provider("openrouter", "OpenRouter", 2, ("RESEARCH_MODEL_PROVIDER", "RESEARCH_MODEL", "OPENROUTER_API_KEY")),
        _model_provider("openai", "OpenAI", 2, ("RESEARCH_MODEL", "OPENAI_API_KEY")),
        _model_provider("compatible", "OpenAI-compatible endpoint (e.g. local Ollama)", 0,
                        ("OPENAI_BASE_URL", "RESEARCH_MODEL", "OPENAI_API_KEY")),
    ]


def _missing(provider: Provider) -> list[str]:
    return provider.missing() if provider.missing else _unset(provider.env)


def status(checks: dict[str, dict]) -> list[dict]:
    """One entry per kind: its providers in priority order and which one is active (the first configured)."""
    kinds = {kind: {"kind": kind, "label": label, "purpose": purpose, "active": None, "providers": []}
             for kind, (label, purpose) in KINDS.items()}
    for provider in all_providers():
        last = checks.get(provider.name)
        configured = provider.configured()
        if last and not last["ok"]:
            state = "check_failed"
        elif not configured:
            state = "not_configured"
        else:
            state = "ready" if not provider.env else "configured"
        kind = kinds[provider.kind]
        if configured and kind["active"] is None:
            kind["active"] = provider.name
        kind["providers"].append({
            "name": provider.name, "label": provider.label, "tier": provider.tier, "env": list(provider.env),
            "configured": configured, "missing_env": [] if configured else _missing(provider), "problem": None if configured else provider.problem(),
            "status": state, "last_check": last, "can_check": provider.check is not None, "note": provider.note or None})
    return [kind for kind in kinds.values() if kind["providers"]]


def run_check(name: str) -> dict:
    """Run one provider's live check. KeyError: no such check. DataError: not configured, so nothing to test."""
    provider = next((p for p in all_providers() if p.name == name), None)
    if provider is None or provider.check is None:
        raise KeyError(name)
    if not provider.configured():
        reason = provider.problem() or f"Set {', '.join(_missing(provider))} in .env."
        raise DataError(f"{provider.label} is not configured yet. {reason} Restart the server after changing .env.",
                        "not_configured")
    try:
        return {"ok": True, "message": provider.check()}
    except Exception as exc:  # a check reports any failure; it never crashes the status page
        ours = isinstance(exc, (DataError, DomainError))  # our own errors already say what went wrong
        return {"ok": False, "message": str(exc) if ours else f"{type(exc).__name__}: {exc}"}
