"""What a 20-F or 40-F cover says about the US-listed shares (REFERENCE §5).

A foreign company's US quote is often an American depositary share (ADS) that stands for several ordinary shares
(BABA: eight), so its market cap needs that ratio. The cover's inline XBRL names each listed class
(`dei:Security12bTitle`); without the tag, the Section 12(b) table in the cover text is read instead. A cover that
lists the shares and only says they trade as ADSs (TSMC) leaves the ratio to the filing's text, if it gives one value.
The text counts only when the cover names ADSs: a plain-share filer's note on another company's ADSs never sets its ratio.
"""
import html
import json
import re
import unicodedata
from datetime import datetime, timezone
from fractions import Fraction

from .. import config
from ..contracts import DomainError
from ..filings import Document
from . import ixbrl
from .cache import DiskCache
from .errors import DataError
from .sec import SecClient
from .sec_filings import Filing

TITLE_TAG = "dei:Security12bTitle"
FILING_TEXT = "filing text"
SHARES_TAG = "dei:EntityCommonStockSharesOutstanding"
# A depositary class in a title; ADS/ADR only in capitals, so "ads" (adverts) never counts.
DEPOSITARY = re.compile(r"(?i:american\s+depositary|depositary\s+(?:shares?|receipts?))|\bAD[SR]s?\b")
# Anywhere in the filing: a company whose shares trade as ADSs names them in full at least once.
MENTIONS_ADS = re.compile(r"american\s+depositary|depositary\s+(?:shares?|receipts?)", re.I)
SHARES = re.compile(r"\b(?:shares?|stock)\b", re.I)
# "each representing eight Ordinary Shares", "every two of which represent three shares", "each ADS represents 1/10 of one".
RATIO = re.compile(
    r"\b(?:each|every)(?:\s+(?P<ads>[\w-]+))?(?:\s+(?:of\s+which|such|ADSs?|ADRs?|American\s+Depositary\s+(?:Shares?|Receipts?)))*"
    r",?\s+(?:represents?|representing|evidenc(?:es|ing))\s+(?P<amount>[\w\s./()-]+?)\s+(?:(?:class|series)\s+\w+\s+)?"
    r"(?:ordinary|common|equity|underlying)?\s*shares?\b", re.I)
COVER_START = re.compile(r"Section\s+12\s*\(\s*b\s*\)\s+of\s+the\s+Act", re.I)
COVER_END = re.compile(r"Section\s+12\s*\(\s*g\s*\)\s+of\s+the\s+Act|Indicate\s+the\s+number\s+of\s+outstanding", re.I)
# The cover page, footnotes included, ends where the filing's contents begin: PART I or ITEM 1, its first entries.
PAGE_END = re.compile(r"\bPART\s+I\b|\bITEM\s+1\b", re.I)
NUMBERS = {"a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8,
           "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14, "fifteen": 15,
           "sixteen": 16, "seventeen": 17, "eighteen": 18, "nineteen": 19, "twenty": 20, "thirty": 30, "forty": 40,
           "fifty": 50, "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90, "hundred": 100}
PARTS = {"half": 2, "halve": 2, "third": 3, "quarter": 4, "fourth": 4, "fifth": 5, "sixth": 6, "seventh": 7,
         "eighth": 8, "ninth": 9, "tenth": 10, "twentieth": 20, "fiftieth": 50, "hundredth": 100}
WELL_GROUPED = re.compile(r"\d{1,3}(?:,\d{3})+|\d+")


def _word_number(text: str) -> int | None:
    """"eight" -> 8, "twenty-five" -> 25, "one hundred" -> 100."""
    words = re.split(r"[\s-]+", text.strip().lower())
    if len(words) == 2 and words[1] == "hundred" and words[0] in NUMBERS:
        return NUMBERS[words[0]] * 100
    if len(words) == 2 and words[0] in NUMBERS and words[1] in NUMBERS and NUMBERS[words[0]] >= 20 > NUMBERS[words[1]]:
        return NUMBERS[words[0]] + NUMBERS[words[1]]
    return NUMBERS.get(words[0]) if len(words) == 1 else None


def amount(text: str) -> Fraction | None:
    """A count of shares in words or digits: "eight", "8", "eight (8)", "0.5", "1/10", "one-half of one"."""
    text = " ".join(text.lower().split())
    if digits := re.search(r"\((\d+(?:\.\d+)?(?:\s*/\s*\d+)?)\)", text):
        text = digits.group(1)  # "eight (8)": the digits decide
    text = re.sub(r"\s+of\s+(?:one|an?)$", "", text).strip()
    if re.fullmatch(r"\d+(?:\.\d+)?", text):
        return Fraction(text)
    if match := re.fullmatch(r"(\d+)\s*/\s*(\d+)", text):
        return Fraction(int(match[1]), int(match[2])) if int(match[2]) else None
    if (match := re.fullmatch(r"([a-z]+(?:[\s-][a-z]+)?)[\s-]([a-z]+?)s?", text)) and match[2] in PARTS:
        top = _word_number(match[1])
        return Fraction(top, PARTS[match[2]]) if top else None
    whole = _word_number(text)
    return Fraction(whole) if whole else None


def ratio(text: str) -> Fraction | None:
    """Ordinary shares per depositary share, from words like "each representing eight Ordinary Shares"."""
    match = RATIO.search(" ".join(text.split()))
    if not match:
        return None
    shares = amount(match["amount"])
    ads = amount(match["ads"]) if match["ads"] else None
    found = shares / (ads or 1) if shares else None
    return found if found and found > 0 else None


def _plain(source: str) -> str:
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", source)).split())


def _shown(doc: Document) -> list[dict]:
    """Each tagged cover share count, and the number the page shows when the tag cuts it off (BABA's 2026 20-F tags
    "18,580,374,27" and prints the last "8" just after the tag)."""
    found = []
    for node in doc.root.nodes("ix:nonfraction"):
        if node.attrs.get("name") != SHARES_TAG:
            continue
        tagged = node.text()
        after = html.unescape(re.sub(r"<[^>]+>", "", doc.source[node.end:node.end + 500]))
        page = tagged + re.match(r"[\d,]*", after).group(0)
        cut = not WELL_GROUPED.fullmatch(tagged) and bool(WELL_GROUPED.fullmatch(page))
        found.append({"tagged": tagged, "shown": page if cut else None})
    return found


def _cover_page(plain: str) -> str:
    """The cover page with its footnotes (TSMC's "* ... American Depositary Shares representing such Common Shares")."""
    start = COVER_START.search(plain)
    end = PAGE_END.search(plain, start.end() if start else 0)
    return plain[:end.start() if end else len(plain)]


def _stated(plain: str) -> dict[Fraction, str]:
    """Each ratio the filing's text gives for its depositary shares, with the first words that give it."""
    found: dict[Fraction, str] = {}
    for match in RATIO.finditer(plain):
        start = match.start() if DEPOSITARY.search(match.group(0)) else next(
            (m.start() for m in reversed(list(DEPOSITARY.finditer(
                plain, max(0, match.start() - config.FILING_RATIO_LOOKBACK_CHARS), match.start())))), None)
        if start is not None and (value := ratio(match.group(0))) is not None:
            found.setdefault(value, plain[start:match.end()])
    return found


def _read(doc: Document) -> dict:
    # Invisible direction marks (Unicode "Cf") sometimes sit inside a title.
    titles = list(dict.fromkeys(clean for t in ixbrl.texts(doc, TITLE_TAG)
                                if (clean := "".join(c for c in t["text"] if unicodedata.category(c) != "Cf").strip())))
    found = {"titles": titles, "ratio": None, "how": None, "basis": None, "problem": None, "shares": _shown(doc)}
    listed = [t for t in titles if DEPOSITARY.search(t)]
    plain = _plain(doc.source)
    start = COVER_START.search(plain)
    end = COVER_END.search(plain, start.end()) if start else None
    cover = plain[start.end():end.start()] if start and end else None
    if not titles and cover and DEPOSITARY.search(cover):  # no tag: each depositary row of the Section 12(b) table
        found["how"] = "cover text"
        rows = {}
        for mention in DEPOSITARY.finditer(cover):
            near = RATIO.search(cover, mention.start(), mention.end() + config.COVER_RATIO_WINDOW_CHARS)
            rows.setdefault(ratio(near.group(0)) if near else None,
                            cover[mention.start():near.end()] if near else cover[mention.start():mention.end()])
        listed = [text for value, text in rows.items() if value is not None] or list(rows.values())[:1]
    if len(listed) > 1:
        found["problem"] = f"The cover lists more than one depositary class ({'; '.join(listed)}), so which one " \
                           "the ticker trades can't be told."
    elif listed:
        found["how"], found["basis"] = found["how"] or TITLE_TAG, listed[0]
        value = ratio(listed[0])
        if value is None:
            found["problem"] = f"How many ordinary shares one depositary share stands for can't be read from " \
                               f"\"{listed[0][:200]}\"."
        found["ratio"] = None if value is None else f"{value.numerator}/{value.denominator}"
    elif DEPOSITARY.search(_cover_page(plain)):  # the filer's own shares trade as ADSs, so the text's ratio is theirs
        if len(stated := _stated(plain)) == 1:
            ((value, words),) = stated.items()
            found.update(ratio=f"{value.numerator}/{value.denominator}", how=FILING_TEXT, basis=words)
        else:
            found["problem"] = (f"The cover mentions American depositary shares, but the cover's listed classes "
                                f"({'; '.join(titles) or 'none tagged'}) give no ratio, and the filing's text states "
                                + (f"more than one: {'; '.join(stated.values())}." if stated else "none."))
    elif titles and any(SHARES.search(t) for t in titles):
        found.update(ratio="1/1", how="no depositary shares", basis="; ".join(titles))
    elif not titles and cover and SHARES.search(cover):
        found.update(ratio="1/1", how="no depositary shares", basis=cover[:300])
    else:
        found["problem"] = "The cover lists no shares on a US exchange" + (f" (only {'; '.join(titles)})." if titles else ".")
    return found


def read(sec: SecClient, filing: Filing, cache: DiskCache) -> dict:
    """The cover's listed classes, ordinary shares per depositary share ("8/1"; "1/1" for a direct listing) and how
    it was read, or the problem; plus each tagged share count. Cached for good, since filings never change."""
    key = f"cover|v3|{filing.url}"  # v3: the filing's text gives the ratio only when the cover names ADSs
    cached = cache.get(key, None)
    if cached is not None:
        return json.loads(cached[0])
    if not filing.primary_document.lower().endswith((".htm", ".html")):
        raise DataError("The filing's main document is not HTML, so its cover can't be read.", "bad_data")
    try:
        found = _read(Document(sec.get(filing.url).body))
    except DomainError as exc:
        raise DataError(f"The filing could not be parsed: {exc}", "bad_data") from exc
    cache.put(key, json.dumps(found).encode(), datetime.now(timezone.utc))
    return found
