"""get_peers: listed companies in the same SIC industry, closest in revenue, and the sector ETF to benchmark against
(REFERENCE §10). The record says exactly how the peers were chosen, because SIC is coarse."""
import json
import math
from datetime import timedelta

from pydantic import BaseModel, Field

from .. import config
from ..data import companies, peers, sec_facts
from ..data.sec import cik10
from .result import Tool, ToolContext, ToolResult, make_id

SOURCE = "SEC company list by SIC + SEC frames"


class GetPeersInput(BaseModel):
    cik: str = Field(min_length=1, max_length=10, description="The company's CIK from find_company.")
    count: int | None = Field(None, ge=1, description=f"Peers to return (default {config.PEERS_DEFAULT_COUNT}).")


def _pool(context: ToolContext, codes: list[int], cik: str, listed: dict) -> dict[str, int]:
    """Listed companies (not the company itself) under each SIC code, with the code they were found under."""
    found: dict[str, int] = {}
    for code in codes:
        for member in peers.members(context.sec, code):
            if member != cik and member in listed:
                found.setdefault(member, code)
    return found


def _ranked(pool: dict[str, int], revenue: dict[str, dict], own) -> list[str]:
    """Closest revenue first (by ratio, so $2bn and $8bn are equally far from $4bn); ties on CIK. Without the
    company's own revenue, the largest first."""
    sized = [c for c in pool if c in revenue and revenue[c]["value"] > 0]
    if own and own["value"] > 0:
        return sorted(sized, key=lambda c: (abs(math.log(revenue[c]["value"] / own["value"])), c))
    return sorted(sized, key=lambda c: (-revenue[c]["value"], c))


def run(args: GetPeersInput, context: ToolContext) -> ToolResult:
    if not args.cik.strip().isdigit():
        return ToolResult(status="invalid", source=SOURCE, warnings=["cik must be digits; use find_company first."])
    cik, count = cik10(args.cik), args.count or config.PEERS_DEFAULT_COUNT
    profile = companies.profile(context.sec, cik)
    sic, name = profile["sic"], profile["name"]
    if sic is None:
        return ToolResult(status="unsupported", source=SOURCE, warnings=[f"{name} has no SIC industry code at SEC."])
    sector = peers.sector_etf(sic)
    warnings = [] if sector else [f"No sector ETF is mapped for SIC {sic} (config.SECTOR_ETFS)."]
    base = {"kind": "peers", "cik": cik, "name": name, "sic": sic, "sic_description": profile["sic_description"],
            "sector": sector, "source": SOURCE, "url": peers.PAGE.format(sic=sic)}
    if context.historical:
        # SEC's list and frames are today's (latest-filed values, today's listed companies), so peers at a past
        # cutoff would use later information; the sector ETF mapping doesn't depend on the date.
        record = base | {"peers": [], "method": "Peers aren't chosen at a past cutoff; only the sector ETF is given."}
        record["id"] = make_id("peers", cik, sic, "historical")
        context.remember(record)
        return ToolResult(status="partial" if sector else "unsupported", data=_shown(record), ids=[record["id"]],
                          source=SOURCE, warnings=warnings + [
                              f"Peers can't be chosen as of a past cutoff ({context.cutoff.date()}): SEC's company "
                              "list and frames are today's. Pick peers yourself and check each with get_financials."])
    year = (context.cutoff.date() - timedelta(days=config.SCREEN_FRAME_LAG_DAYS)).year - 1
    revenue = sec_facts.frame(context.sec, sec_facts.CONCEPTS["revenue"], year)
    listed = companies.listed_companies(context.sec)
    pool = _pool(context, [sic], cik, listed)
    widened = len(_ranked(pool, revenue, None)) < count
    if widened:  # too few with revenue: add the other codes of the same three-digit industry group
        group = sic // 10 * 10
        pool |= {c: code for c, code in _pool(context, [s for s in range(group, group + 10) if s != sic], cik,
                                               listed).items() if c not in pool}
    own = revenue.get(cik)
    chosen = _ranked(pool, revenue, own)[:count]
    where = f"SIC {sic} ({profile['sic_description']})" + (
        f", widened to SIC {group:04d}-{group + 9:04d} because fewer than {count} had revenue" if widened else "")
    size = (f"closest {year} revenue in SEC frames to {name}'s" if own and own["value"] > 0 else
            f"largest {year} revenue in SEC frames ({name} has none there)")
    method = (f"Companies in SEC's ticker list today under {where}, ranked by {size}. {len(pool)} listed companies "
              f"considered; {len(pool) - len(_ranked(pool, revenue, None))} had no positive revenue in the frame.")
    shown = [{"cik": c, "name": listed[c].name, "tickers": list(listed[c].tickers), "sic": pool[c],
              "revenue": str(revenue[c]["value"]), "revenue_end": revenue[c].get("end"),
              "size_vs_company": round(float(revenue[c]["value"] / own["value"]), 2) if own and own["value"] > 0 else None}
             for c in chosen]
    record = base | {"peers": shown, "method": method, "widened": widened, "year": year, "considered": len(pool),
                     "own_revenue": str(own["value"]) if own else None}
    record["id"] = make_id("peers", cik, sic, year, count, json.dumps(shown, sort_keys=True))
    context.remember(record)
    warnings += ["SIC codes are coarse and today's (Amazon is still catalog retail): check each peer really competes, "
                 "and say how they were chosen.",
                 "Revenue here only ranks peers: SEC frames hold latest-filed (restated) values. Use get_financials "
                 "for each peer's figures."]
    if len(chosen) < count:
        warnings.append(f"Only {len(chosen)} peers found with revenue, fewer than the {count} asked for.")
    return ToolResult(status="ok", data=_shown(record), ids=[record["id"]], source=SOURCE, warnings=warnings)


def _shown(record: dict) -> dict:
    tip = (f"Fetch {record['sector']['ticker']} with get_prices and compare with calculate total_return, "
           "relative_return or beta." if record["sector"] else None)
    return {"id": record["id"], "company": record["name"], "sic": record["sic"],
            "sic_description": record["sic_description"], "method": record["method"], "peers": record["peers"],
            "sector_benchmark": record["sector"], "next": tip}


TOOL = Tool("get_peers", "Peers for a company: listed companies with the same SIC industry code (widened to the "
            "three-digit group if too few), closest in revenue, and the sector ETF (e.g. XLK) to benchmark against. "
            "Says how the peers were chosen; get each peer's figures with get_financials.", GetPeersInput, run, SOURCE)
