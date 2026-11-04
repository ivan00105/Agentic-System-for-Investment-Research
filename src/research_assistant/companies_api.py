"""Company search for the web page's picker (PROJECT_GUIDE Phase 7): SEC's current ticker list, as the user types,
and the bundled Discover universes the page offers besides the user's own list."""
from datetime import date
from typing import Annotated

from fastapi import APIRouter, Query

from . import cli
from .contracts import DomainError
from .data import universe
from .data.companies import suggest
from .data.errors import DataError

router = APIRouter(prefix="/api/companies")
universes = APIRouter(prefix="/api/universes")


@router.get("")
def companies(q: Annotated[str, Query(max_length=200)] = ""):
    with cli.sec_client() as sec:
        try:
            found, total = suggest(sec, q)
        except DataError as exc:  # degrade: the question box still takes typed names
            raise DomainError(f"Company search is unavailable: {exc}", exc.code,
                              409 if exc.code == "not_configured" else 503) from exc
    return {"items": [{"cik": c.cik, "name": c.name, "tickers": list(c.tickers), "exchanges": list(c.exchanges)}
                      for c in found], "total": total}


@universes.get("")
def bundled():
    """The bundled lists, then every SEC filer with a ticker, which needs SEC access (said so, never an error)."""
    found = [(name, universe.load(name)) for name in universe.bundled()]
    items = [{"id": name, "name": u.name, "companies": len(u.ciks), "as_of": u.as_of, "note": u.note,
              "available": True, "problem": None, "dynamic": False} for name, u in found]
    everyone = {"id": universe.ALL_FILERS, "name": "Every SEC filer with a ticker", "companies": None,
                "as_of": date.today().isoformat(), "note": universe.ALL_FILERS_NOTE, "available": False,
                "problem": None, "dynamic": True}
    with cli.sec_client() as sec:
        try:
            everyone.update(companies=len(universe.all_filers(sec).ciks), available=True)
        except (universe.UniverseError, DataError) as exc:
            everyone["problem"] = f"Unavailable: {exc}"
    return {"items": [*items, everyone]}
