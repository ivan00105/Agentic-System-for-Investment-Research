"""Declared Discover universes (REFERENCE §4): a named list of companies with its source and date.

A universe lists today's members, so it is a survivorship-biased snapshot; Discover always says which one it used.
"""
from dataclasses import dataclass
from importlib.resources import files
from pathlib import Path

import yaml

from .sec import cik10

BUNDLED = files(__package__).joinpath("universes")


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

    @property
    def ciks(self) -> list[str]:
        """One CIK per issuer: share classes (GOOG and GOOGL) are one company."""
        return list(dict.fromkeys(m.cik for m in self.members))


def bundled() -> list[str]:
    return sorted(p.name.removesuffix(".yaml") for p in BUNDLED.iterdir() if p.name.endswith(".yaml"))


def load(name_or_path: str) -> Universe:
    """A bundled universe by name (e.g. sp500_tech), or any YAML file of the same shape."""
    path = Path(name_or_path)
    source = path if path.suffix in (".yaml", ".yml") else BUNDLED.joinpath(f"{name_or_path}.yaml")
    if not source.is_file():
        raise UniverseError(f"No universe {name_or_path!r}: give a YAML file or one of {', '.join(bundled())}.")
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
