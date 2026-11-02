"""find_company: resolve a ticker, CIK or name to SEC filers, with industry and filer flags."""
from pydantic import BaseModel, Field

from ..data import companies
from ..data.errors import DataError
from .result import Tool, ToolContext, ToolResult


class FindCompanyInput(BaseModel):
    query: str = Field(min_length=1, max_length=200, description="A ticker (AAPL, BRK.B), a CIK, or a company name.")


def run(args: FindCompanyInput, context: ToolContext) -> ToolResult:
    matches, total = companies.search(context.sec, args.query)
    if not matches:
        return ToolResult(status="not_found", source="SEC company tickers", warnings=[
            f"No SEC filer matches {args.query!r}. Try the exact ticker or the legal name."])
    warnings = []
    if total > len(matches):
        warnings.append(f"{total} companies match; showing the best {len(matches)}. Use a ticker or CIK to narrow it.")
    rows, ids = [], []
    for match in matches:
        company = match.company
        record = {"id": f"company-{company.cik}", "kind": "company", "cik": company.cik, "name": company.name,
                  "tickers": list(company.tickers), "exchanges": list(company.exchanges), "listed": company.listed,
                  "score": match.score}
        if not company.listed:
            warnings.append(f"{company.name} is not in SEC's current ticker list: it may be delisted, renamed or never listed.")
        rows.append(record)
        ids.append(context.remember(record))
    source = "SEC company tickers" if matches[0].company.listed else "SEC all-filer names"
    if len(rows) == 1:
        # One clear answer: add the industry and filer facts the analysts need to pick their tools.
        try:
            details = companies.profile(context.sec, rows[0]["cik"])
        except DataError as exc:
            warnings.append(f"Industry and filer details are unavailable: {exc}")
            return ToolResult(status="ok", data={"matches": rows}, ids=ids, source=source, warnings=warnings)
        rows[0].update(details, id=rows[0]["id"], kind="company", listed=rows[0]["listed"], score=rows[0]["score"])
        context.remember(rows[0])
        source += " + SEC submissions"
        if details["foreign_filer"]:
            warnings.append("Foreign private issuer (files 20-F/40-F): financials in IFRS or in a currency other "
                            "than USD come back unsupported from get_financials.")
        if not details["has_annual_report"]:
            warnings.append("No annual report in the last year of filings: a new registrant (e.g. after a "
                            "reorganisation) may keep its history under a predecessor CIK; search the former name.")
        if details["financial_sector"]:
            warnings.append(f"Financial company (SIC {details['sic']}, {details['sic_description']}): operating income "
                            "and gross profit are usually not reported, so margins built on them are unsupported.")
    return ToolResult(status="ok", data={"matches": rows}, ids=ids, source=source, warnings=warnings)


TOOL = Tool("find_company", "Find a US-listed company by ticker, CIK or name. Returns its SEC CIK, tickers, "
            "industry (SIC) and flags for banks/insurers and foreign (IFRS) filers. Call this first.",
            FindCompanyInput, run, "SEC company tickers")
