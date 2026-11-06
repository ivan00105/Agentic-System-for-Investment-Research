"""The report's figures for the web page (PROJECT_GUIDE Phase 7): a key-numbers table, and small charts of revenue,
margin and price per company. Everything comes from the records frozen in the run's trace, so nothing is fetched."""
from datetime import date
from decimal import Decimal

from ..finance import fundamentals
from .checker import format_value
from .sources import MARGINS, label, period

CHANGES = ("growth", "change_pp")
MARGIN_TOPS = ("operating_income", "net_income")  # banks report no operating income, so net margin stands in


def figures(cited: list[str], key_numbers: list[str], records: dict[str, dict]) -> dict:
    """`cited`: every record the report cites, in order; `key_numbers`: those the key-numbers section cites."""
    names = {r["cik"]: r.get("name") for r in records.values() if r.get("kind") == "company"}
    ciks = list(dict.fromkeys(r["cik"] for i in cited if (r := records.get(i)) and r.get("kind") == "fact" and r.get("cik")))
    return {"table": table(key_numbers, records, names),
            "charts": [chart(cik, names.get(cik) or cik, records, set(cited)) for cik in ciks]}


def table(ids: list[str], records: dict[str, dict], names: dict[str, str]) -> list[dict]:
    """One row per cited figure; a growth or change_pp calc on that figure fills its change column."""
    cited = [r for i in dict.fromkeys(ids) if (r := records.get(i)) and r.get("kind") in ("fact", "calc")]
    rows = [_row(r, records, names) for r in cited if r.get("formula") not in CHANGES]
    changes = [r for r in records.values() if r.get("formula") in CHANGES and r.get("value") is not None]
    cited_ids, used = {r["id"] for r in cited}, set()
    for row in rows:  # a cited change first, then any the run computed on the same figure
        change = next((c for c in sorted(changes, key=lambda c: c["id"] not in cited_ids)
                       if c["inputs"].get("current") == row["id"]), None)
        if change:
            row.update(change=format_value(change), change_id=change["id"])
            used.add(change["id"])
    rows += [_row(r, records, names) for r in cited if r.get("formula") in CHANGES and r["id"] not in used]
    return rows


def _row(record: dict, records: dict[str, dict], names: dict[str, str]) -> dict:
    value = format_value(record) if record.get("value") is not None else f"unavailable: {record.get('reason')}"
    return {"id": record["id"], "company": names.get(record.get("cik")) or record.get("cik"),
            "metric": label(record, records), "period": period(record, records), "value": value,
            "change": None, "change_id": None}


def chart(cik: str, company: str, records: dict[str, dict], cited: set[str]) -> dict:
    """The price line is the longest series the report cites (else the longest saved), on adjusted closes: an
    as-traded close drops at every split (NVIDIA's 10-for-1 in 2024 looked like a crash)."""
    revenue = _annual(cik, "revenue", records)
    top_metric = next((m for m in MARGIN_TOPS if set(_annual(cik, m, records)) & set(revenue)), None)
    tops = _annual(cik, top_metric, records) if top_metric else {}
    margin = []
    for end in sorted(set(revenue) & set(tops)):
        outcome = fundamentals.ratio(Decimal(tops[end]["value"]), Decimal(revenue[end]["value"]))
        if outcome.value is not None:
            margin.append({"end": end, "value": float(outcome.value), "ids": [tops[end]["id"], revenue[end]["id"]],
                           "label": format_value({"value": outcome.value, "unit": "ratio"})})
    series = [r for r in records.values() if r.get("kind") == "prices" and r.get("cik") == cik and r.get("rows")]
    prices = max(series, key=lambda r: (r["id"] in cited, len(r["rows"]), r["id"]), default=None)
    return {"cik": cik, "company": company,
            "revenue": [{"end": end, "value": float(r["value"]), "label": format_value(r), "ids": [r["id"]]}
                        for end, r in sorted(revenue.items())],
            "margin": {"label": MARGINS[top_metric] if margin else None, "points": margin},
            "price": prices and {"id": prices["id"], "ticker": prices.get("ticker"), "source": prices.get("source"),
                                 "points": [[r["date"], r["adj_close"]] for r in prices["rows"]
                                            if r.get("adj_close") is not None]}}


def raw(cited: list[str], records: dict[str, dict]) -> list[dict]:
    """Every reported figure and calculation the report cites, and every input behind them, unformatted: the
    Professional view's table and the CSV/JSON export."""
    names = {r["cik"]: r.get("name") for r in records.values() if r.get("kind") == "company"}
    rows, seen, queue = [], set(), list(cited)
    while queue:
        record = records.get(queue.pop(0))
        if not record or record["id"] in seen or record.get("kind") not in ("fact", "calc"):
            continue
        seen.add(record["id"])
        inputs = {role: i for role, i in (record.get("inputs") or {}).items() if isinstance(i, str)}
        queue += list(inputs.values())
        shown = _row(record, records, names)
        rows.append({"id": record["id"], "kind": record["kind"], "cik": record.get("cik"), "company": shown["company"],
                     "label": shown["metric"], "period": shown["period"], "value": record.get("value"),
                     "unit": record.get("unit"), "shown": shown["value"],
                     "start": record.get("start"), "end": record.get("end"), "formula": record.get("formula"),
                     "inputs": inputs, "tag": record.get("tag"), "form": record.get("form"),
                     "accession": record.get("accession"), "filed": record.get("filed"),
                     "url": record.get("filing_url"), "notes": record.get("notes") or [],
                     "reason": record.get("reason")})
    return rows


def _annual(cik: str, metric: str, records: dict[str, dict]) -> dict[str, dict]:
    """A company's fiscal-year values of one metric by period end; a period filed twice keeps the later filing."""
    found: dict[str, dict] = {}
    for r in records.values():
        if r.get("kind") == "fact" and r.get("cik") == cik and r.get("metric") == metric and r.get("start") and \
                350 <= (date.fromisoformat(r["end"]) - date.fromisoformat(r["start"])).days <= 380:
            if r["end"] not in found or (r.get("filed"), r["id"]) > (found[r["end"]].get("filed"), found[r["end"]]["id"]):
                found[r["end"]] = r
    return found
