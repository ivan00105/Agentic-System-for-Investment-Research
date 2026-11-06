"""How the web page names and shows a cited record: a short label for its citation chip, the group it is listed
under, and what the evidence panel shows when the chip is opened. Read from the frozen records, never fetched."""
import re
from datetime import date
from decimal import Decimal

from .checker import format_value

GROUPS = {"fact": "Reported figures", "calc": "Calculations", "chunk": "Filing text", "filing": "Filings",
          "prices": "Prices", "check": "Checks against the filing", "company": "Companies",
          "claim": "Analyst findings", "calendar": "Release dates", "insider": "Insider trades",
          "peers": "Peers and sector"}
METRICS = {"revenue": "Revenue", "gross_profit": "Gross profit", "operating_income": "Operating income",
           "net_income": "Net income", "research_and_development": "R&D spending",
           "operating_cash_flow": "Operating cash flow", "capex": "Capital spending", "eps_diluted": "Diluted EPS",
           "diluted_shares": "Diluted shares", "total_assets": "Total assets", "total_liabilities": "Total liabilities",
           "stockholders_equity": "Shareholders' equity", "cash": "Cash", "long_term_debt": "Long-term debt",
           "shares_outstanding": "Shares outstanding"}
FORMULAS = {"fcf": "Free cash flow", "market_cap": "Market cap", "pe": "P/E", "ps": "P/S", "pb": "P/B",
            "fcf_yield": "FCF yield", "ev": "Enterprise value", "total_return": "Total return",
            "volatility": "Volatility", "max_drawdown": "Largest fall from a peak", "beta": "Beta",
            "sharpe": "Sharpe ratio", "relative_return": "Return against the benchmark"}
MARGINS = {"gross_profit": "Gross margin", "operating_income": "Operating margin", "net_income": "Net margin",
           "fcf": "FCF margin", "operating_cash_flow": "Operating cash flow margin"}


def label(record: dict | None, records: dict[str, dict]) -> str:
    """What a fact or calc measures, in words: "Revenue", "Operating margin", "Revenue growth"."""
    if record is None:
        return "Unknown record"
    if record.get("kind") == "fact":
        metric = record.get("metric")
        return METRICS.get(metric) or record.get("label") or str(metric).replace("_", " ").capitalize()
    formula, inputs = record.get("formula"), record.get("inputs") or {}

    def of(role):
        return label(records.get(inputs.get(role)), records)
    if formula == "ratio":
        top, bottom = records.get(inputs.get("numerator")) or {}, records.get(inputs.get("denominator")) or {}
        if bottom.get("metric") == "revenue" and (name := MARGINS.get(top.get("metric") or top.get("formula"))):
            return name
        return f"{of('numerator')} / {of('denominator')}"
    if formula in ("growth", "cagr"):
        return f"{of('current' if formula == 'growth' else 'last')} {'growth' if formula == 'growth' else 'CAGR'}"
    if formula == "change_pp":
        return f"Change in {of('current')[:1].lower()}{of('current')[1:]}"
    return FORMULAS.get(formula, str(formula))


def period(record: dict, records: dict[str, dict]) -> str:
    """"year ended 2025-09-27", "at 2026-07-17", or for a change "year ended 2025-09-27 vs 2024-09-28"."""
    if record.get("formula") in ("growth", "change_pp"):
        current, previous = (records.get((record.get("inputs") or {}).get(r)) for r in ("current", "previous"))
        if current and previous:
            return f"{period(current, records)} vs {previous.get('end')}"
    start, end = record.get("start"), record.get("end")
    if not end:
        return ""
    if not start:
        return f"at {end}"
    days = (date.fromisoformat(end) - date.fromisoformat(start)).days
    return f"year ended {end}" if 350 <= days <= 380 else f"quarter ended {end}" if 80 <= days <= 100 \
        else f"{start} to {end}"


def item(section: str | None) -> str:
    """"part_ii_item_7" -> "Item 7", "part_i_item_1a" -> "Item 1A", an 8-K's "item_202" -> "Item 2.02"."""
    match = re.search(r"item_(\d+)([a-z]?)$", section or "")
    if not match:
        return (section or "section").replace("_", " ")
    digits, letter = match.groups()
    return f"Item {digits[0]}.{digits[1:]}" if len(digits) == 3 else f"Item {digits}{letter.upper()}"


def chip(record: dict | None, records: dict[str, dict]) -> str:
    """A citation chip's few words."""
    kind = (record or {}).get("kind")
    if kind in ("fact", "calc"):
        end = record.get("end")
        return f"{label(record, records)}{f' {end[:4]}' if end else ''}"
    if kind == "chunk":  # which year's filing, when the run listed it
        filed = str((records.get(f"filing-{record.get('accession')}") or {}).get("filed", ""))[:4]
        return f"{record.get('form')}{f' {filed}' if filed else ''} {item(record.get('section'))} ¶{record.get('n')}"
    if kind == "filing":
        return f"{record.get('form')} {str(record.get('filed', ''))[:10]}"
    if kind == "prices":
        return f"{record.get('ticker')} prices"
    if kind == "check":
        return f"Filing check: {record.get('verdict')}"
    if kind == "calendar":
        return f"Release dates from {record.get('start')}"
    if kind == "peers":
        return f"Peers of {record.get('name')}"
    if kind == "insider":
        return f"Form 4 {record.get('meaning')} {record.get('date')}"
    if kind == "company":
        return str(record.get("name"))
    if kind == "claim":
        return f"{str(record.get('author', '')).capitalize()} finding"
    return (record or {}).get("id", "source")


def detail(record: dict, records: dict[str, dict]) -> dict:
    """What the evidence panel shows: a title, the excerpt itself, facts about it, and records it links to."""
    kind, rows, links = record.get("kind"), [], []
    title, excerpt, url = chip(record, records), "", record.get("filing_url") or record.get("url")
    if kind == "fact" and not record.get("accession"):  # a value from another provider, e.g. get_macro's rates
        title = f"{label(record, records)}, {period(record, records)}"
        excerpt = format_value(record)
        rows = [("Source", record.get("source")), ("Series", record.get("series_id")),
                ("Definition", record.get("definition")), ("As published on", record.get("vintage"))]
        rows += [("Note", note) for note in record.get("notes") or []]
        links = list(record.get("trades") or [])
    elif kind == "fact":
        title = f"{label(record, records)}, {period(record, records)}"
        excerpt = format_value(record)
        rows = [("Reported as", record.get("tag")), ("Filing", f"{record.get('form')} {record.get('accession')}"),
                ("Filed", record.get("filed"))]
        if record.get("original_value") is not None:
            rows.append(("First reported as", f"{record['original_value']} in {record.get('original_accession')}"))
    elif kind == "calc":
        title = f"{label(record, records)}, {period(record, records)}"
        excerpt = format_value(record) if record.get("value") is not None else f"Unavailable: {record.get('reason')}"
        rows = [("Formula", record.get("formula"))] + [("Note", note) for note in record.get("notes") or []]
        links = [i for i in (record.get("inputs") or {}).values() if isinstance(i, str)]
    elif kind == "chunk":
        title = f"{record.get('form')} {record.get('accession')}, {item(record.get('section'))}, paragraph {record.get('n')}"
        excerpt = record.get("text", "")
    elif kind == "filing":
        title = f"{record.get('form')} filed {record.get('filed')}"
        excerpt = record.get("description") or ""
        rows = [("Period", record.get("report_date")), ("Accepted", record.get("accepted_at")),
                ("8-K items", ", ".join(map(_item, record.get("items") or [])) or None)]
    elif kind == "prices":
        closes = [r for r in record.get("rows") or [] if r.get("close") is not None]
        title = f"{record.get('ticker')} daily prices, {record.get('start')} to {record.get('end')}"
        excerpt = (f"{len(closes)} trading days. Last close {closes[-1]['close']:.2f} on {closes[-1]['date']} "
                   "(as traded).") if closes else "No closing prices."
        rows = [("Source", record.get("source")),
                ("Adjusted prices", "Include dividends, so nobody could have traded at them")]
    elif kind == "peers":
        title = f"Peers of {record.get('name')} (SIC {record.get('sic')}, {record.get('sic_description')})"
        excerpt = "; ".join(f"{p['name']} ({', '.join(p['tickers'])})" for p in record.get("peers") or []) or "None chosen."
        rows = [("How they were chosen", record.get("method")),
                ("Sector benchmark", (record.get("sector") or {}).get("rule"))]
    elif kind == "insider":
        title = f"Insider {record.get('meaning')} by {record.get('owner')}, {record.get('date')}"
        value = f" (${Decimal(record['value']):,.0f})" if record.get("value") else ""
        excerpt = f"{record.get('shares')} shares of {record.get('security')} at ${record.get('price')}{value}"
        rows = [("Role", record.get("role")), ("Code", f"{record.get('code')} ({record.get('meaning')})"),
                ("10b5-1 plan", f"yes ({record.get('plan_basis')})" if record.get("plan_10b5_1") else "no"),
                ("Shares owned after", record.get("owned_after")),
                ("Held", "directly" if record.get("direct") else "indirectly"),
                ("Filing", f"Form {record.get('form')} {record.get('accession')}, filed {record.get('filed')}")]
        rows += [("Footnote", note) for note in record.get("footnotes") or []]
    elif kind == "calendar":
        title = f"Release dates, {record.get('start')} to {record.get('end')}"
        excerpt = "; ".join(f"{r['date']}: {r['name']}" for r in record.get("releases") or []) or "No major releases."
        rows = [("Source", record.get("source"))] + [("Note", note) for note in record.get("notes") or []]
    elif kind == "check":
        title = f"Check of {label(records.get(record.get('fact_id')), records).lower()} against the filing"
        excerpt = f"{record.get('verdict')}: expected {record.get('expected')}"
        rows = [("Found", found.get("row")) for found in record.get("found") or []]
        links = [record["fact_id"]] if record.get("fact_id") else []
    elif kind == "company":
        title = str(record.get("name"))
        excerpt = f"CIK {record.get('cik')}, {', '.join(record.get('tickers') or []) or 'no ticker'}"
        rows = [("Industry", record.get("sic_description")), ("Fiscal year ends", record.get("fiscal_year_end")),
                ("Bank or insurer", "yes" if record.get("financial_sector") else None),
                ("Foreign filer", "yes" if record.get("foreign_filer") else None)]
    elif kind == "claim":
        title = f"{str(record.get('author', '')).capitalize()} analyst finding, version {record.get('version')}"
        excerpt = record.get("text", "")
        links = list(record.get("citations") or [])
    return {"id": record["id"], "kind": kind, "group": GROUPS.get(kind, "Other"), "title": title, "excerpt": excerpt,
            "available_at": record.get("available_at"), "url": url,
            "rows": [{"label": k, "value": str(v)} for k, v in rows if v is not None],
            "links": [{"id": i, "label": chip(records.get(i), records)} for i in links if i in records]}


def _item(entry) -> str:
    """An 8-K item as list_filings stores it ({code, name}), or a plain code from older traces."""
    return f"{entry.get('code')} {entry.get('name')}" if isinstance(entry, dict) else str(entry)
