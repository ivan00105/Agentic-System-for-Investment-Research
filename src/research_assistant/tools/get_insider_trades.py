"""get_insider_trades: insiders' open-market buys and sales from their Form 4 filings, each one citable, with totals
as facts (REFERENCE §10). Only codes P and S count; a sale under a 10b5-1 plan was scheduled in advance, so it is
flagged."""
import re
from collections import Counter
from datetime import date, timedelta
from decimal import Decimal

from pydantic import BaseModel, Field

from .. import config
from ..data import companies, sec_insiders
from ..data.sec import cik10
from .result import Tool, ToolContext, ToolResult, make_id

SOURCE = "SEC Form 4"
PLAN = re.compile(r"10b-?5-1", re.IGNORECASE)
NOT_PLAN = re.compile(r"\bnot\b[^.]{0,60}10b-?5-1", re.IGNORECASE)  # "was not made under a Rule 10b5-1 plan"
# The meaning of each total, its unit, and which trades it adds up.
TOTALS = {
    "insider_purchases": ("Insider purchases", "USD"), "insider_sales": ("Insider sales", "USD"),
    "insider_sales_planned": ("Insider sales under 10b5-1 plans", "USD"),
    "insider_net_purchases": ("Insider net purchases", "USD"), "insider_buyers": ("Insiders who bought", "insiders"),
}


class GetInsiderTradesInput(BaseModel):
    cik: str = Field(min_length=1, max_length=10, description="The company's CIK from find_company.")
    since: date | None = Field(None, description=f"First trade date; default {config.INSIDER_LOOKBACK_DAYS} days "
                               "before the cutoff.")


def _planned(trade: dict, plan_box: bool) -> str | None:
    """Why a trade counts as under a 10b5-1 plan: its footnote says so, or the form's 10b5-1 box is ticked."""
    if any(NOT_PLAN.search(note) for note in trade["footnotes"]):
        return None
    if any(PLAN.search(note) for note in trade["footnotes"]):
        return "footnote"
    return "form's 10b5-1 box" if plan_box else None


def _trade(cik: str, filing, parsed: dict, index: int, trade: dict) -> dict:
    value = (trade["shares"] * trade["price"]).quantize(Decimal(1)) if trade["shares"] and trade["price"] else None
    basis = _planned(trade, parsed["plan_box"])
    return {"id": make_id("insider", filing.accession, index), "kind": "insider", "cik": cik,
            "owner": "; ".join(o["name"] for o in parsed["owners"]) or "not stated",
            "role": "; ".join(dict.fromkeys(o["role"] for o in parsed["owners"])) or "not stated",
            "date": trade["date"], "code": trade["code"], "meaning": sec_insiders.CODES.get(trade["code"], "unknown code"),
            "security": trade["security"], "shares": str(trade["shares"]) if trade["shares"] is not None else None,
            "price": str(trade["price"]) if trade["price"] is not None else None,
            "value": str(value) if value is not None else None,
            "owned_after": str(trade["owned_after"]) if trade["owned_after"] is not None else None,
            "direct": trade["direct"], "plan_10b5_1": basis is not None, "plan_basis": basis,
            "footnotes": trade["footnotes"], "form": filing.form, "accession": filing.accession,
            "filed": filing.filed.isoformat(),
            "available_at": filing.accepted_at.isoformat() if filing.accepted_at else None, "url": filing.url}


def _total(cik: str, metric: str, value: Decimal, trades: list[dict], start: date, end: date, note: str) -> dict:
    label, unit = TOTALS[metric]
    ids = [t["id"] for t in trades]
    return {"id": make_id("fact", "insider", cik, metric, start, end, value, *ids), "kind": "fact", "cik": cik,
            "metric": metric, "label": label, "value": str(value), "unit": unit, "start": start.isoformat(),
            "end": end.isoformat(), "source": SOURCE, "trades": ids, "notes": [note],
            "url": f"https://www.sec.gov/cgi-bin/own-disp?action=getissuer&CIK={cik}"}


def _totals(cik: str, trades: list[dict], start: date, end: date) -> list[dict]:
    buys = [t for t in trades if t["code"] == "P" and t["value"]]
    sales = [t for t in trades if t["code"] == "S" and t["value"]]
    planned = [t for t in sales if t["plan_10b5_1"]]

    def total(rows):
        return sum((Decimal(t["value"]) for t in rows), Decimal(0))
    return [
        _total(cik, "insider_purchases", total(buys), buys, start, end, f"{len(buys)} purchase(s) (code P)."),
        _total(cik, "insider_sales", total(sales), sales, start, end, f"{len(sales)} sale(s) (code S)."),
        _total(cik, "insider_sales_planned", total(planned), planned, start, end,
               f"{len(planned)} of the sales were under a 10b5-1 plan, set up in advance."),
        _total(cik, "insider_net_purchases", total(buys) - total(sales), buys + sales, start, end,
               "Purchases minus sales, at the prices reported."),
        _total(cik, "insider_buyers", Decimal(len({t["owner"] for t in buys})), buys, start, end,
               "Different reporting owners with at least one purchase."),
    ]


def run(args: GetInsiderTradesInput, context: ToolContext) -> ToolResult:
    if not args.cik.strip().isdigit():
        return ToolResult(status="invalid", source=SOURCE, warnings=["cik must be digits; use find_company first."])
    cik = cik10(args.cik)
    end = context.cutoff.date()
    start = args.since or end - timedelta(days=config.INSIDER_LOOKBACK_DAYS)
    if start > end:
        return ToolResult(status="invalid", source=SOURCE, warnings=[f"since {start} is after the cutoff {end}."])
    if companies.profile(context.sec, cik)["foreign_filer"]:
        return ToolResult(status="unsupported", source=SOURCE, warnings=[
            "Foreign private issuers (20-F/40-F filers) are exempt from Section 16, so their insiders file no Form 4: "
            "no trades here doesn't mean nobody traded."])
    filings, notes = sec_insiders.read(context.sec, cik, context.cutoff, start)
    trades, other, unpriced = [], Counter(), 0
    for filing, parsed in filings:
        other.update(f"{c} (derivative)" for c in parsed["derivative_codes"])
        for index, row in enumerate(parsed["trades"]):
            if not (start.isoformat() <= row["date"] <= end.isoformat()):
                continue  # a late Form 4 can report a trade from before the window
            if row["code"] not in sec_insiders.SIGNALS:
                other[row["code"]] += 1
                continue
            trade = _trade(cik, filing, parsed, index, row)
            unpriced += trade["value"] is None
            context.remember(trade)
            trades.append(trade)
    trades.sort(key=lambda t: (t["date"], t["id"]), reverse=True)
    totals = _totals(cik, trades, start, end)
    for record in totals:
        context.remember(record)
    warnings = notes + ([f"{unpriced} trade(s) report no price or share count and are left out of the totals; each "
                         "one's record says what was filed."] if unpriced else [])
    data = {"cik": cik, "start": start.isoformat(), "end": end.isoformat(), "filings_read": len(filings),
            "totals": {r["metric"]: {"id": r["id"], "value": r["value"], "unit": r["unit"]} for r in totals},
            "trades": [{"id": t["id"], "date": t["date"], "owner": t["owner"], "role": t["role"], "code": t["code"],
                        "shares": t["shares"], "price": t["price"], "value": t["value"],
                        "plan_10b5_1": t["plan_10b5_1"], "filed": t["filed"]} for t in trades],
            "not_counted": {code: {"meaning": sec_insiders.CODES.get(code.split()[0], "unknown code"), "transactions": n}
                            for code, n in sorted(other.items())},
            "how_to_read": "Only P (purchase) and S (sale) are an insider's own decision to buy or sell. Codes in "
                           "not_counted (tax withholding, option exercises, grants, gifts) are not signals. A sale under "
                           "a 10b5-1 plan was scheduled months ahead, so it says little about the insider's view now."}
    return ToolResult(status="ok", data=data, ids=[t["id"] for t in trades] + [r["id"] for r in totals],
                      source=SOURCE, warnings=warnings)


TOOL = Tool("get_insider_trades", "Insiders' open-market purchases (code P) and sales (code S) from their SEC Form 4 "
            "filings, by default over the last year: each trade is a citable record (who, role, date, shares, price, "
            "10b5-1 plan or not), and the totals (purchases, sales, planned sales, net purchases, number of buyers) "
            "are fact IDs. Tax withholding, option exercises and gifts are counted but not treated as buys or sales.",
            GetInsiderTradesInput, run, SOURCE)
