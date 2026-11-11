"""list_filings: a company's SEC filings as of the cutoff, newest first, with 8-K event types."""
from datetime import date

from pydantic import BaseModel, Field

from .. import config
from ..data import sec_filings
from ..data.sec import cik10
from .result import Tool, ToolContext, ToolResult


class ListFilingsInput(BaseModel):
    cik: str = Field(pattern=r"^[0-9]{1,10}$", description="The company's CIK from find_company.")
    forms: list[str] | None = Field(None, description='Form types to keep, e.g. ["8-K"] or ["10-K", "10-Q"]; omit for all.')
    since: date | None = Field(None, description="Earliest filing date to include.")
    page: str | None = Field(None, pattern=r"^\d{4}-\d{2}-\d{2}/\d{10}-\d{2}-\d{6}$",
                             description="next_page from the previous result, to continue exactly where it stopped.")
    limit: int | None = Field(None, ge=1, description=f"Most filings to return (default {config.LIST_FILINGS_MAX_RESULTS}).")


def run(args: ListFilingsInput, context: ToolContext) -> ToolResult:
    cik = cik10(args.cik)
    limit = args.limit or config.LIST_FILINGS_MAX_RESULTS
    forms = {f.strip().upper() for f in args.forms} if args.forms else None
    after = None
    if args.page:
        day, accession = args.page.split("/")
        after = (date.fromisoformat(day), accession)
    found = sec_filings.search(context.sec, cik, context.cutoff, forms=forms, since=args.since, after=after,
                               limit=limit + 1)
    warnings, next_page = [], None
    if forms and (hidden := sorted(forms & sec_filings.RELEASED_LATER)):
        warnings.append(f"{', '.join(hidden)} never listed: {sec_filings.RELEASED_LATER_WHY}.")
    if len(found) > limit:
        found = found[:limit]
        next_page = f"{found[-1].filed}/{found[-1].accession}"
        warnings.append(f"More filings match than the {limit} shown; narrow with forms or since, or pass "
                        f"page={next_page} for the next ones.")
    rows, ids = [], []
    for filing in found:
        record = {"id": f"filing-{filing.accession}", "kind": "filing", "cik": cik, "accession": filing.accession,
                  "form": filing.form, "filed": filing.filed.isoformat(),
                  "accepted_at": filing.accepted_at.isoformat() if filing.accepted_at else None,
                  "report_date": filing.report_date.isoformat() if filing.report_date else None,
                  "items": [{"code": code, "name": sec_filings.EIGHT_K_ITEMS.get(code, "Unknown item")} for code in filing.items],
                  "description": filing.description, "url": filing.url}
        ids.append(context.remember(record))
        rows.append({k: v for k, v in record.items() if k not in ("kind", "cik")})
    if not rows:
        warnings.append("No filings match before the cutoff.")
    return ToolResult(status="ok", data={"cik": cik, "filings": rows, "next_page": next_page}, ids=ids,
                      source="SEC submissions", warnings=warnings)


TOOL = Tool("list_filings", "A company's SEC filings up to the research cutoff, newest first: form, filing and "
            "acceptance time, event or period date, and 8-K item types (earnings, executive changes, deals...). "
            "Use forms=[\"8-K\"] for events. Drafts and SEC review letters (DRS, CORRESP, UPLOAD) are never listed.",
            ListFilingsInput, run, "SEC submissions")
