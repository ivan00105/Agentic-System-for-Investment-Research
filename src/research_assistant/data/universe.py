"""Declared Discover universes (REFERENCE §4): a named list of companies with its source and date.

A universe lists today's members, so it is a survivorship-biased snapshot; Discover always says which one it used.
Besides the bundled files there is one built from SEC's ticker list on the day (`ALL_FILERS`).
"""
from dataclasses import dataclass
from datetime import date
from importlib.resources import files
from pathlib import Path

import yaml

from .companies import listed_companies, normalize_ticker
from .sec import SecClient, cik10

BUNDLED = files(__package__).joinpath("universes")
ALL_FILERS = "sec_all"
# Measured 5 Nov 2026 on a cold cache (REFERENCE §4): 8,004 companies screened in 11 s from 9 SEC frames requests.
ALL_FILERS_NOTE = ("Every company in SEC's ticker list today (Nasdaq, NYSE, Cboe and OTC), so close to the whole "
                   "US-listed market, but today's companies only (survivorship bias). Funds, foreign filers and "
                   "shells mostly come back unknown. Screening fundamentals takes seconds; a sector filter reads each "
                   "passing company's SEC profile (about 1,200 downloads, several minutes the first time each day).")


class UniverseError(ValueError):
    """The universe can't be read; the message says what to fix."""


@dataclass(frozen=True)
class Member:
    ticker: str
    cik: str
    name: str
    sector: str | None = None


@dataclass(frozen=True)
class Universe:
    name: str
    source: str
    as_of: str
    note: str
    members: tuple[Member, ...]
    show_members: bool = True  # False: too many to list in the screener's prompt, which gets the size instead

    @property
    def ciks(self) -> list[str]:
        """One CIK per issuer: share classes (GOOG and GOOGL) are one company."""
        return list(dict.fromkeys(m.cik for m in self.members))


def bundled() -> list[str]:
    return sorted(p.name.removesuffix(".yaml") for p in BUNDLED.iterdir() if p.name.endswith(".yaml"))


def load(name_or_path: str, sec: SecClient | None = None) -> Universe:
    """A bundled universe by name (e.g. sp500_tech), `ALL_FILERS` (needs `sec`), or any YAML file of the same shape."""
    if name_or_path == ALL_FILERS:
        if sec is None:
            raise UniverseError(f"{ALL_FILERS} is built from SEC's ticker list, so it needs SEC access.")
        return all_filers(sec)
    path = Path(name_or_path)
    source = path if path.suffix in (".yaml", ".yml") else BUNDLED.joinpath(f"{name_or_path}.yaml")
    if not source.is_file():
        raise UniverseError(f"No universe {name_or_path!r}: give a YAML file or one of "
                            f"{', '.join([*bundled(), ALL_FILERS])}.")
    try:
        data = yaml.safe_load(source.read_text(encoding="utf-8"))
        members = tuple(Member(str(c["ticker"]), cik10(str(c["cik"])), str(c["name"]), c.get("sector"))
                        for c in data["companies"])
        universe = Universe(str(data["name"]), str(data["source"]), str(data["as_of"]), str(data.get("note", "")),
                            members)
    except (yaml.YAMLError, KeyError, TypeError) as exc:
        raise UniverseError(f"{source} is not a universe file (needs name, source, as_of and companies with "
                            f"ticker, cik and name): {exc}") from exc
    if not members:
        raise UniverseError(f"{source} lists no companies.")
    return universe


def all_filers(sec: SecClient) -> Universe:
    """Every SEC filer with a ticker today, one member per ticker (share classes and preferreds count once)."""
    listed = sorted(listed_companies(sec).values(), key=lambda c: c.cik)
    members = tuple(Member(t, c.cik, c.name) for c in listed for t in c.tickers)
    if not members:
        raise UniverseError("SEC's ticker list came back empty.")
    return Universe("Every SEC filer with a ticker", "SEC's company_tickers_exchange.json", date.today().isoformat(),
                    ALL_FILERS_NOTE, members, show_members=False)


def from_tickers(sec: SecClient, tickers: list[str]) -> Universe:
    """The user's own list (the web page's "my own list of tickers"), checked against SEC's current tickers."""
    listed = {t: c for c in listed_companies(sec).values() for t in c.tickers}
    wanted = list(dict.fromkeys(normalize_ticker(t) for t in tickers if t.strip()))
    unknown = [t for t in wanted if t not in listed]
    if unknown:
        raise UniverseError(f"Not in SEC's current ticker list: {', '.join(unknown)}.")
    if not wanted:
        raise UniverseError("The list has no tickers.")
    members = tuple(Member(t, listed[t].cik, listed[t].name) for t in wanted)
    return Universe("your list", "tickers you entered, checked against SEC's company_tickers_exchange.json",
                    date.today().isoformat(), "Chosen by the user: a hand-picked list, not an index or the market.",
                    members)
