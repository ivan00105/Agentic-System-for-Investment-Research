"""Insider trades from SEC Form 4 (REFERENCE §10): one ownership XML per filing, read with the standard library.

Only codes P (open-market or private purchase) and S (sale) are an insider's own buy or sell decision. The rest,
such as F (shares withheld for tax), M (option exercise) and G (gift), are counted but are not signals.
Codes: https://www.sec.gov/about/forms/form4data.pdf (Form 4, General Instruction 8).
"""
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from .. import config
from . import sec_filings
from .errors import DataError
from .sec import SecClient

FORMS = {"4", "4/A"}
SIGNALS = {"P", "S"}
CODES = {
    "P": "purchase", "S": "sale", "A": "grant or award", "D": "sale back to the company", "F": "shares withheld for tax",
    "I": "discretionary plan trade", "M": "option exercise", "C": "conversion", "E": "expiry of a short derivative",
    "H": "expiry of a long derivative", "O": "out-of-the-money exercise", "X": "in-the-money exercise", "G": "gift",
    "L": "small acquisition", "W": "inheritance", "Z": "voting trust deposit or withdrawal", "J": "other",
    "K": "equity swap", "U": "tender in a change of control", "V": "voluntarily reported earlier",
}


def _text(node, path: str) -> str:
    found = node.find(path) if node is not None else None
    return (found.text or "").strip() if found is not None and found.text else ""


def _number(text: str) -> Decimal | None:
    try:
        return Decimal(text) if text else None
    except InvalidOperation:
        return None


def _role(relationship) -> str:
    roles = []
    if _text(relationship, "isDirector") in ("1", "true"):
        roles.append("director")
    if _text(relationship, "isOfficer") in ("1", "true"):
        roles.append(_text(relationship, "officerTitle") or "officer")
    if _text(relationship, "isTenPercentOwner") in ("1", "true"):
        roles.append("10% owner")
    if _text(relationship, "isOther") in ("1", "true"):
        roles.append(_text(relationship, "otherText") or "other")
    return ", ".join(roles) or "not stated"


def parse(body: bytes) -> dict:
    """Owners, the 10b5-1 box, footnotes, non-derivative transactions and the codes of derivative ones."""
    try:
        root = ET.fromstring(body)
    except ET.ParseError as exc:
        raise DataError(f"Not an ownership XML: {exc}", "bad_data") from exc
    if root.tag != "ownershipDocument":  # e.g. an error page, which would read as a filing with no trades
        raise DataError(f"Not an ownership XML: its root is <{root.tag}>.", "bad_data")
    owners = [{"cik": _text(o, "reportingOwnerId/rptOwnerCik"), "name": _text(o, "reportingOwnerId/rptOwnerName"),
               "role": _role(o.find("reportingOwnerRelationship"))} for o in root.findall("reportingOwner")]
    footnotes = {f.get("id"): " ".join((f.text or "").split()) for f in root.findall("footnotes/footnote")}
    trades = []
    for row in root.findall("nonDerivativeTable/nonDerivativeTransaction"):
        refs = [f.get("id") for f in row.iter("footnoteId")]
        trades.append({
            "security": _text(row, "securityTitle/value"), "date": _text(row, "transactionDate/value"),
            "code": _text(row, "transactionCoding/transactionCode"),
            "shares": _number(_text(row, "transactionAmounts/transactionShares/value")),
            "price": _number(_text(row, "transactionAmounts/transactionPricePerShare/value")),
            "acquired_disposed": _text(row, "transactionAmounts/transactionAcquiredDisposedCode/value"),
            "owned_after": _number(_text(row, "postTransactionAmounts/sharesOwnedFollowingTransaction/value")),
            "direct": _text(row, "ownershipNature/directOrIndirectOwnership/value") != "I",
            "footnotes": [footnotes[i] for i in refs if i in footnotes]})
    derivative = [_text(row, "transactionCoding/transactionCode")
                  for row in root.findall("derivativeTable/derivativeTransaction")]
    return {"owners": owners, "plan_box": _text(root, "aff10b5One") in ("1", "true"), "trades": trades,
            "derivative_codes": [c for c in derivative if c]}


def xml_url(filing: sec_filings.Filing) -> str | None:
    """The raw XML behind a Form 4 (its primary document is an XSL rendering, e.g. xslF345X06/form4.xml)."""
    name = filing.primary_document.rsplit("/", 1)[-1]
    return filing.folder_url + name if name.lower().endswith(".xml") else None


def read(sec: SecClient, cik: str, cutoff: datetime,
         since: date) -> tuple[list[tuple[sec_filings.Filing, dict]], list[str], int]:
    """Every Form 4 filed from `since` and public at the cutoff, parsed; notes on filings that weren't read; and how
    many Form 4s couldn't be read (amendments are skipped on purpose, so they don't count). Archived filings never
    change, so each XML is cached for good after its first download."""
    filings = sec_filings.search(sec, cik, cutoff, forms=FORMS, since=since)
    amended = [f for f in filings if f.form == "4/A"]
    readable = [f for f in filings if f.form == "4" and xml_url(f)]
    notes = [f"Form 4 {f.accession} has no XML; not read." for f in filings if f.form == "4" and not xml_url(f)]
    if amended:  # an amendment restates a Form 4 that is already counted, so reading both would count it twice
        notes.append(f"{len(amended)} amendment(s) (4/A) not read: {', '.join(f.accession for f in amended)}. Each "
                     "restates an earlier Form 4, which is counted as first filed.")

    def one(filing):
        try:
            return filing, parse(sec.get(xml_url(filing)).body), None
        except DataError as exc:
            return filing, None, f"{filing.form} {filing.accession} could not be read: {exc}"
    # Parallel downloads still share SEC's 10-per-second limiter.
    with ThreadPoolExecutor(max_workers=config.INSIDER_FETCH_WORKERS) as pool:
        results = list(pool.map(one, readable))
    notes += [note for _, _, note in results if note]
    parsed = [(f, found) for f, found, _ in results if found is not None]
    return parsed, notes, len([f for f in filings if f.form == "4"]) - len(parsed)
