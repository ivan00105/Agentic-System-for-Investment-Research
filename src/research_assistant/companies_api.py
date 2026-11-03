"""Company search for the web page's picker (PROJECT_GUIDE Phase 7): SEC's current ticker list, as the user types."""
from typing import Annotated

from fastapi import APIRouter, Query

from . import cli
from .contracts import DomainError
from .data.companies import suggest
from .data.errors import DataError

router = APIRouter(prefix="/api/companies")


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
