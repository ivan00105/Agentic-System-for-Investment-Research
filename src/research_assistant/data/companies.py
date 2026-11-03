"""Company identity from SEC: current tickers, every filer name ever used, and the SIC industry code."""
import json
import re
from dataclasses import dataclass
from functools import lru_cache

from rapidfuzz import fuzz, process, utils

from .. import config
from .sec import SecClient, cik10

TICKERS_URL = "https://www.sec.gov/files/company_tickers_exchange.json"
# Every name any filer has used, including delisted and renamed companies (several MB, refreshed daily).
ALL_NAMES_URL = "https://www.sec.gov/Archives/edgar/cik-lookup-data.txt"
FOREIGN_ANNUAL_FORMS = {"20-F", "20-F/A", "40-F", "40-F/A"}


@dataclass(frozen=True)
class Company:
    cik: str
    name: str
    tickers: tuple[str, ...] = ()  # several when an issuer has share classes (GOOG, GOOGL)
    exchanges: tuple[str, ...] = ()
    listed: bool = True  # False: only in SEC's all-filers name list (delisted, renamed or never listed)


@dataclass(frozen=True)
class Match:
    company: Company
    score: float  # 100 for an exact ticker or CIK


def normalize_ticker(text: str) -> str:
    return text.strip().upper().replace(".", "-")


def is_financial_sic(sic: int | None) -> bool:
    """Banks, credit, brokers and insurers (SIC 6000-6499): they don't report operating income or gross profit."""
    return sic is not None and 6000 <= sic <= 6499


def listed_companies(sec: SecClient) -> dict[str, Company]:
    return _parse_tickers(sec.get(TICKERS_URL).body)


@lru_cache(maxsize=2)
def _parse_tickers(body: bytes) -> dict[str, Company]:
    payload = json.loads(body)
    columns = {name: i for i, name in enumerate(payload["fields"])}
    grouped: dict[str, dict] = {}
    for row in payload["data"]:
        cik = cik10(row[columns["cik"]])
        entry = grouped.setdefault(cik, {"name": row[columns["name"]], "tickers": [], "exchanges": []})
        entry["tickers"].append(row[columns["ticker"]])
        if row[columns["exchange"]] and row[columns["exchange"]] not in entry["exchanges"]:
            entry["exchanges"].append(row[columns["exchange"]])
    return {cik: Company(cik, e["name"], tuple(e["tickers"]), tuple(e["exchanges"])) for cik, e in grouped.items()}


@lru_cache(maxsize=2)
def _parse_all_names(body: bytes) -> dict[str, Company]:
    # Lines look like "APPLE INC:0000320193:". Names can contain colons, so split from the right.
    companies = {}
    for line in body.decode("latin-1").splitlines():
        name, _, rest = line.rstrip(":").rpartition(":")
        if name and rest.isdigit():
            companies.setdefault(cik10(rest), Company(cik10(rest), name, listed=False))
    return companies


def search(sec: SecClient, query: str) -> tuple[list[Match], int]:
    """Matches best first, and how many there were in total (more than the config limit are not returned)."""
    text = query.strip()
    listed = listed_companies(sec)
    cik = re.fullmatch(r"(?:CIK)?\s*([0-9]{1,10})", text, re.IGNORECASE)
    if cik:
        company = listed.get(cik10(cik[1])) or _parse_all_names(sec.get(ALL_NAMES_URL).body).get(cik10(cik[1]))
        return ([Match(company, 100.0)], 1) if company else ([], 0)
    ticker = normalize_ticker(text)
    exact = [c for c in listed.values() if ticker in c.tickers]
    if exact:
        return [Match(c, 100.0) for c in sorted(exact, key=lambda c: c.cik)], len(exact)
    matches = _fuzzy(text, listed)
    if not matches:
        matches = _fuzzy(text, _parse_all_names(sec.get(ALL_NAMES_URL).body))
    return matches[:config.FIND_COMPANY_MAX_MATCHES], len(matches)


def suggest(sec: SecClient, query: str) -> tuple[list[Company], int]:
    """Listed companies for a search box as the user types: the exact ticker, then tickers starting with the text,
    then the closest names. Current tickers only, so a typo never fetches SEC's all-filers list."""
    text = query.strip()
    if not text:
        return [], 0
    listed = listed_companies(sec)
    order = {cik: i for i, cik in enumerate(listed)}  # SEC's file lists the largest companies first
    ticker = normalize_ticker(text)
    by_ticker = sorted((c for c in listed.values() if any(t.startswith(ticker) for t in c.tickers)),
                       key=lambda c: (ticker not in c.tickers, order[c.cik]))
    seen = {c.cik for c in by_ticker}
    found = by_ticker + [m.company for m in _fuzzy(text, listed) if m.company.cik not in seen]
    return found[:config.COMPANY_SUGGEST_MAX], len(found)


def _fuzzy(text: str, companies: dict[str, Company]) -> list[Match]:
    names = {cik: company.name for cik, company in companies.items()}
    found = process.extract(text, names, scorer=fuzz.WRatio, processor=utils.default_process,
                            score_cutoff=config.FIND_COMPANY_MIN_SCORE, limit=None)
    # Ties: closer full-name similarity first, then the stable CIK (never alphabetical by design).
    found.sort(key=lambda hit: (-hit[1], -fuzz.ratio(text, hit[0], processor=utils.default_process), hit[2]))
    return [Match(companies[cik], round(score, 1)) for _, score, cik in found]


def profile(sec: SecClient, cik: str) -> dict:
    """Identity details from the submissions JSON: industry, fiscal year end and what the company files."""
    payload = sec.submissions(cik).json()
    forms = set(payload.get("filings", {}).get("recent", {}).get("form", []))
    sic = int(payload["sic"]) if str(payload.get("sic", "")).isdigit() else None
    return {
        "cik": cik10(payload["cik"]), "name": payload.get("name"), "tickers": payload.get("tickers", []),
        "exchanges": payload.get("exchanges", []), "sic": sic, "sic_description": payload.get("sicDescription"),
        "sec_office": payload.get("ownerOrg"), "fiscal_year_end": payload.get("fiscalYearEnd"),
        "state_of_incorporation": payload.get("stateOfIncorporation"), "filer_category": payload.get("category"),
        "entity_type": payload.get("entityType"),
        "former_names": [n.get("name") for n in payload.get("formerNames", [])],
        "foreign_filer": bool(forms & FOREIGN_ANNUAL_FORMS) and not forms & {"10-K", "10-K/A"},
        # SEC's recent block always covers at least a year, so a missing annual report is meaningful.
        "has_annual_report": bool(forms & (FOREIGN_ANNUAL_FORMS | {"10-K", "10-K/A"})),
        "financial_sector": is_financial_sic(sic),
    }
