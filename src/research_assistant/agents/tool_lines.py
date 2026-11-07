"""One tool call in plain words: what it asked for, for which company and period, and what came out. Read from the
call's arguments and result and the records earlier calls froze in the trace, never fetched."""
from collections import Counter

from .checker import format_value
from .sources import METRICS, item, label, period

STATUS = {"ok": "OK", "partial": "partial", "unsupported": "unsupported", "not_found": "not found",
          "unavailable": "unavailable", "invalid": "invalid", "repeat": "repeated"}
# Each tool's title on its own line, and how a step counts its calls: one call, several calls.
TOOLS = {
    "find_company": ("Company lookup", "company lookup", "company lookups"),
    "get_financials": ("Reported figures", "reported figures", "requests for reported figures"),
    "calculate": ("Calculation", "calculation", "calculations"),
    "get_prices": ("Prices", "price history", "price histories"),
    "read_filing_section": ("Filing section", "filing section", "filing sections"),
    "list_filings": ("Filing list", "filing list", "filing lists"),
    "verify_against_filing": ("Check against the filing", "check against the filing", "checks against the filing"),
    "get_peers": ("Peers", "peer search", "peer searches"),
    "get_macro": ("Economic data", "economic data", "requests for economic data"),
    "get_insider_trades": ("Insider trades", "insider trades", "requests for insider trades"),
    "screen": ("Screen", "screen", "screens"),
    "ask_fundamentals": ("Fundamentals analyst", "fundamentals analyst", "questions to the fundamentals analyst"),
    "ask_filings": ("Filings analyst", "filings analyst", "questions to the filings analyst"),
    "ask_market": ("Market analyst", "market analyst", "questions to the market analyst"),
    "submit_report": ("Handing in the report", "handing in the report", "reports handed in"),
    "submit_findings": ("Handing in findings", "handing in findings", "findings handed in"),
    "submit_objections": ("Handing in objections", "handing in objections", "objections handed in"),
    "submit_revision": ("Handing in the revision", "handing in the revision", "revisions handed in"),
    "submit_screen_spec": ("Handing in the screen spec", "handing in the screen spec", "screen specs handed in"),
}
# Formulas named after their inputs ("Gross margin"), for when those inputs weren't frozen in the trace.
FORMULAS = {"ratio": "Ratio", "growth": "Growth", "cagr": "Yearly growth (CAGR)", "change_pp": "Change in points"}
# Plain names for the filing sections agents read most; others show their item number only.
SECTIONS = {("10-K", "part_i_item_1"): "Business", ("10-K", "part_i_item_1a"): "Risk factors",
            ("10-K", "part_ii_item_7"): "MD&A (management's discussion)", ("10-K", "part_ii_item_7a"): "Market risk",
            ("10-K", "part_ii_item_8"): "Financial statements", ("10-Q", "part_i_item_2"): "MD&A (management's discussion)",
            ("10-Q", "part_ii_item_1a"): "Risk factors"}


class Seen:
    """What a run's earlier events showed: every frozen record by ID, and a short name for each company."""

    def __init__(self):
        self.records: dict[str, dict] = {}
        self.tickers: dict[str, str] = {}
        self.names: dict[str, str] = {}

    def add(self, event: dict):
        records = event.get("records") if isinstance(event.get("records"), dict) else {}
        self.records.update(records)
        data = _data(event)
        listed = [row for key in ("matches", "candidates", "peers") for row in data.get(key) or []]
        for found in [*records.values(), data, *listed]:  # old traces froze no records
            if isinstance(found, dict) and (cik := _cik(found.get("cik"))):
                if ticker := found.get("ticker") or next(iter(found.get("tickers") or []), None):
                    self.tickers.setdefault(cik, ticker)
                if found.get("kind") in ("company", None) and found.get("name"):
                    self.names.setdefault(cik, found["name"])

    def who(self, cik) -> str:
        """A company's ticker, else its name, else its CIK."""
        cik = _cik(cik)
        return self.tickers.get(cik) or self.names.get(cik) or (f"CIK {cik}" if cik else "an unnamed company")


def count(names: list[str]) -> str:
    """The tools a step asked for: "10 calculations", "company lookup, reported figures"."""
    parts = []
    for name, times in Counter(names).items():
        _, one, many = TOOLS.get(name, (name, name, f"{name} calls"))
        parts.append(one if times == 1 else f"{times} {many}")
    return ", ".join(parts)


def status(event: dict) -> str:
    """ok, partial, ... from the result; "repeat" for a call skipped because it repeated an earlier one."""
    return "repeat" if event.get("repeat_of") else str((event.get("result") or {}).get("status"))


def line(event: dict, seen: Seen) -> str:
    """"Calculation: Gross margin, AAPL, year ended 2025-09-27 → OK, 46.9%". A call that failed shows its reason;
    its arguments are left out, since the tool may not have accepted them."""
    name, result = event.get("name"), event.get("result") or {}
    state, warnings = result.get("status"), result.get("warnings") or []
    title = TOOLS.get(name, (str(name),))[0]
    args = event.get("arguments") if isinstance(event.get("arguments"), dict) else {}
    accepted = state in ("ok", "partial", "unsupported")
    what, got = DESCRIBE[name](args, _data(event), seen) if accepted and name in DESCRIBE else ("", "")
    outcome = STATUS.get(state, str(state))
    if state in ("ok", "partial") and got:
        outcome += f", {got}"
    elif state != "ok" and warnings:
        outcome += f": {warnings[0]}"
    return f"{title}{f': {what}' if what else ''} → {outcome}" + (" (repeat)" if event.get("repeat_of") else "")


def _find_company(args, data, seen):
    matches = data.get("matches") or []
    first = matches[0] if matches else {}
    tickers = ", ".join(first.get("tickers") or [])
    got = f"{first.get('name')}{f' ({tickers})' if tickers else ''}" if first else "no match"
    return f'"{args.get("query")}"', got + (f" and {len(matches) - 1} more" if len(matches) > 1 else "")


def _get_financials(args, data, seen):
    metrics = args.get("metrics") or []
    wanted = ", ".join(_lower(METRICS.get(m, str(m).replace("_", " "))) for m in metrics) or "the main figures"
    years = f", {_n(args['years'], 'year')}" if args.get("years") else ""
    ends = data.get("fiscal_year_ends") or []
    missing = [_lower(METRICS.get(m, m)) for m, v in (data.get("metrics") or {}).items() if v.get("status") != "ok"]
    got = (f"{_n(len(ends), 'fiscal year')} to {ends[0]}" if ends else "") + (
        f"; none for {', '.join(missing)}" if missing else "")
    return f"{wanted} for {seen.who(data.get('cik') or args.get('cik'))}{years}", got.removeprefix("; ")


def _calculate(args, data, seen):
    record = data or {}
    inputs = [i for i in (record.get("inputs") or {}).values() if isinstance(i, str)]
    known = all(i in seen.records for i in inputs)  # traces saved before evidence was frozen hold no records
    formula = record.get("formula")
    name = FORMULAS[formula] if formula in FORMULAS and not known else label(record, seen.records)
    # A benchmark such as SPY has no CIK; its price series still names it.
    company = seen.who(record["cik"]) if record.get("cik") else next(
        (r["ticker"] for i in inputs if (r := seen.records.get(i)) and r.get("ticker")), None)
    got = format_value(record) if record.get("value") is not None else ""
    return ", ".join(p for p in (name, company, period(record, seen.records)) if p), got


def _get_prices(args, data, seen):
    span = f", {data['start']} to {data['end']}" if data.get("start") and data.get("end") else ""
    days = _n(data["trading_days"], "trading day") if data.get("trading_days") is not None else ""
    return f"{data.get('ticker') or args.get('ticker')}{span}", days


def _read_filing_section(args, data, seen):
    filing = data.get("filing") or {}
    form, section = str(filing.get("form") or ""), data.get("section")
    name = SECTIONS.get((form.removesuffix("/A"), section))
    if not name and (listed := seen.records.get(f"filing-{filing.get('accession')}")):  # an 8-K item's own name
        code = item(section).removeprefix("Item ")
        name = next((i.get("name") for i in listed.get("items") or [] if isinstance(i, dict) and i.get("code") == code), None)
    where = f"{item(section)}{f' {name}' if name else ''}, {seen.who(args.get('cik'))} {form} {str(filing.get('filed', ''))[:4]}"
    search = f', search "{data["query"]}"' if data.get("query") else ""
    page = f", from paragraph {args['start_chunk']}" if args.get("start_chunk") else ""
    chunks, total = data.get("chunks") or [], data.get("total_chunks")
    return where.strip() + search + page, f"{len(chunks)} of {_n(total, 'paragraph')}" if total is not None else ""


def _list_filings(args, data, seen):
    forms = ", ".join(f"Form {f}" if str(f).isdigit() else str(f) for f in args.get("forms") or []) or "all forms"
    since = f" since {args['since']}" if args.get("since") else ""
    filings = data.get("filings") or []
    return (f"{forms} for {seen.who(data.get('cik') or args.get('cik'))}{since}",
            _n(len(filings), "filing") + (", more to page through" if data.get("next_page") else ""))


def _verify(args, data, seen):
    fact = seen.records.get(data.get("fact_id") or args.get("fact_id"))
    what = (f"{label(fact, seen.records)}, {seen.who(fact.get('cik'))}, {period(fact, seen.records)}"
            if fact else str(data.get("concept") or args.get("fact_id")))
    verdict = data.get("verdict")
    return what, {"match": "matches the filing", "mismatch": "does not match the filing",
                  "not_in_filing": "not in the filing", "unverified": "could not be read"}.get(verdict, verdict or "")


def _get_peers(args, data, seen):
    peers = data.get("peers") or []
    tickers = ", ".join(next(iter(p.get("tickers") or []), p.get("name")) for p in peers)
    return data.get("company") or seen.who(args.get("cik")), _n(len(peers), "peer") + (f" ({tickers})" if tickers else "")


def _get_macro(args, data, seen):
    series = [str(s.get("label") or s.get("name")) for s in data.get("series") or []]
    return ", ".join(series or args.get("series") or []), f"as of {data['as_of']}" if data.get("as_of") else ""


def _insider_trades(args, data, seen):
    span = f", {data['start']} to {data['end']}" if data.get("start") and data.get("end") else ""
    trades = data.get("trades") or []
    return (f"{seen.who(data.get('cik') or args.get('cik'))}{span}",
            f"{_n(len(trades), 'trade')} from {_n(data.get('filings_read') or 0, 'filing')}")


def _screen(args, data, seen):
    spec, counts = data.get("spec") or args, data.get("counts") or {}
    filters = len(spec.get("filters") or [])
    ranked = f", ranked by {str(spec['rank_by']).replace('_', ' ')}" if spec.get("rank_by") else ""
    screened = f"{_n(counts['screened'], 'company')}, " if "screened" in counts else ""
    returned = _n(counts["returned"], "candidate") if "returned" in counts else ""
    return f"{screened}{_n(filters, 'filter')}{ranked}", returned


def _ask(args, data, seen):  # the analyst's own task line shows what was asked
    findings, gaps = len(data.get("findings") or []), len(data.get("gaps") or [])
    stopped = f" ({str(data['status']).replace('_', ' ')})" if data.get("status") not in (None, "finished") else ""
    return "", f"{_n(findings, 'finding')}, {_n(gaps, 'gap')}{stopped}"


DESCRIBE = {"find_company": _find_company, "get_financials": _get_financials, "calculate": _calculate,
            "get_prices": _get_prices, "read_filing_section": _read_filing_section, "list_filings": _list_filings,
            "verify_against_filing": _verify, "get_peers": _get_peers, "get_macro": _get_macro,
            "get_insider_trades": _insider_trades, "screen": _screen,
            "ask_fundamentals": _ask, "ask_filings": _ask, "ask_market": _ask}


def _data(event: dict) -> dict:
    data = (event.get("result") or {}).get("data") if isinstance(event.get("result"), dict) else None
    return data if isinstance(data, dict) else {}


def _cik(cik) -> str | None:
    return str(cik).zfill(10) if cik and str(cik).isdigit() else None


def _n(number, word: str) -> str:
    """"1 filing", "3 filings", "2 companies"."""
    plural = word[:-1] + "ies" if word.endswith("y") and word[-2:-1] not in "aeiou" else word + "s"
    return f"{number} {word if number == 1 else plural}"


def _lower(text: str) -> str:
    """"Gross margin" -> "gross margin", but "P/E" and "FCF yield" keep their capitals."""
    return text[:1].lower() + text[1:] if text[1:2].islower() else text
