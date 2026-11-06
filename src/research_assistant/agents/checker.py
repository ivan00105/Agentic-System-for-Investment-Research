"""The deterministic checker: fills {fact:ID}/{calc:ID} placeholders from tool records and flags anything
that can't be traced to a tool result. It never rejects a draft (PROJECT_GUIDE §5 rule 6)."""
import re
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal

from .. import config
from .draft import SECTIONS, Claim, Draft

# Tolerates spaces and a dash instead of the colon: {fact:fact-1a2b}, {fact: 1a2b}, {calc-1a2b}.
PLACEHOLDER = re.compile(r"\{\s*(fact|calc)\s*[:-]\s*([A-Za-z0-9_.-]+?)\s*\}")
ALLOWED_NUMBERS = re.compile("|".join(config.CHECKER_ALLOWED_NUMBER_PATTERNS))
KINDS = "fact|calc|chunk|filing|company|prices|check|screen|claim|calendar|insider"
# A citation as models write it: fact-1a2b, fact:1a2b, {calc:1a2b} or {chunk: 0000-...}.
CITATION = re.compile(rf"\{{?\s*({KINDS})\s*:\s*([A-Za-z0-9_.-]+?)\s*\}}?")
# A record ID written in the text is a misplaced citation, not a typed figure.
RECORD_ID = re.compile(rf"\b(?:{KINDS})-[A-Za-z0-9_.-]+")
# A record ID cut to its last parts ("-7-11" for chunk-...-item_7-11, live check 3 Nov 2026) is no figure either.
ID_SUFFIX = re.compile(r"(?<![\w.])-\d+(?:-\d+)+(?![\w.%])")
# Digits glued to a word are names (H20, COVID-19, B200), not figures.
TYPED_NUMBER = re.compile(r"(?<![\w.-])[$€£]?[-+]?\d[\d,.]*(?:\s?(?:%|pp\b|x\b|bn\b|billion|million|thousand|trillion))?")
SCALES = ((Decimal(10) ** 12, "trillion"), (Decimal(10) ** 9, "billion"), (Decimal(10) ** 6, "million"))
# A direction word right before a change figure: "fell {calc:ID}", "grew by {calc:ID}", "a decline of {calc:ID}".
DOWN = "fell|falls?|falling|declined|declines?|decreased|decreases?|dropped|drops?|shrank|shrunk|contracted|slipped|" \
       "slid|eroded|compressed|narrowed|lost|down"
UP = "rose|rises?|risen|grew|grows?|growing|increased|increases?|gained|gains?|climbed|expanded|improved|widened|up"
DIRECTION = re.compile(rf"\b(?:({DOWN})|({UP}))\s+(?:by\s+|of\s+)?$", re.IGNORECASE)
CHANGES = {"growth", "change_pp", "cagr", "total_return", "max_drawdown"}


@dataclass
class Flag:
    where: str  # the draft location, e.g. "risks[1]" (JSON path, counting from 0)
    problem: str


@dataclass
class CheckedClaim:
    text: str  # placeholders filled
    kind: str
    citations: list[str]  # IDs that resolved, in order of first use
    flags: list[Flag] = field(default_factory=list)
    materiality: str = "supporting"
    id: str | None = None  # claim ID and version, set by claims.ClaimLedger (REFERENCE §3)
    version: int | None = None

    @property
    def status(self) -> str:
        # "cited" means every citation resolved and nothing was flagged. Whether the cited
        # evidence really supports the statement is judged in evaluation, not here.
        return "qualified" if self.flags else "cited"


@dataclass
class CheckedReport:
    sections: dict[str, list[CheckedClaim]]
    limitations: list[str]
    flags: list[Flag]  # every flag, claims and limitations alike
    sources: list[str]  # every resolved ID cited anywhere, in order of first use

    def section_status(self, key: str) -> str:
        claims = self.sections[key]
        if not claims:
            return "abstained"
        return "qualified" if any(c.flags for c in claims) else "cited"


def check(draft: Draft, records: dict[str, dict]) -> CheckedReport:
    sections = {key: check_claims(getattr(draft, key), key, records) for key, _ in SECTIONS}
    flags = [flag for claims in sections.values() for claim in claims for flag in claim.flags]
    sources = list(dict.fromkeys(i for claims in sections.values() for claim in claims for i in claim.citations))
    limitations = []
    for i, text in enumerate(draft.limitations):
        filled, used, problems = fill(text, f"limitations[{i}]", records)
        limitations.append(filled)
        flags += problems
        sources += [i for i in used if i not in sources]
    return CheckedReport(sections, limitations, flags, sources)


def check_claims(claims: list[Claim], name: str, records: dict[str, dict]) -> list[CheckedClaim]:
    """Check one list of claims, e.g. a report section or an analyst's findings, labelled name[0], name[1]..."""
    return [_claim(claim, f"{name}[{i}]", records) for i, claim in enumerate(claims)]


def _claim(claim: Claim, where: str, records: dict[str, dict]) -> CheckedClaim:
    text, used, flags = fill(claim.text, where, records)
    cited = []
    for raw in claim.citations:
        match = CITATION.fullmatch(raw.strip())
        found = lookup(records, match[2], match[1]) if match else lookup(records, raw.strip())
        if found is None:
            flags.append(Flag(where, f"Citation {raw!r} is not an ID any tool returned in this run."))
        else:  # an analyst's finding (condition C) brings the records it cites, and its flags
            cited += [found["id"], *(found.get("citations") or [])] if found.get("kind") == "claim" else [found["id"]]
            if found.get("kind") == "claim" and found.get("flags"):
                flags.append(Flag(where, f"Cites claim {found['id']}, which was flagged: {'; '.join(found['flags'])}"))
    citations = list(dict.fromkeys(used + cited))
    if not citations:
        flags.append(Flag(where, "No citation: cite the records this statement rests on."))
    return CheckedClaim(text, claim.kind, citations, flags, claim.materiality)


def lookup(records: dict[str, dict], raw: str, kind: str | None = None) -> dict | None:
    """An ID as written, or with its kind prefix added (models sometimes drop it)."""
    return records.get(raw) or (records.get(f"{kind}-{raw}") if kind else None)


def fill(text: str, where: str, records: dict[str, dict]) -> tuple[str, list[str], list[Flag]]:
    """Returns the text with placeholders filled, the IDs used, and flags."""
    used, flags = [], []

    def replace(match: re.Match) -> str:
        kind, raw = match[1], match[2]
        record = lookup(records, raw, kind)
        if record is None:
            flags.append(Flag(where, f"{{{kind}:{raw}}} is not an ID any tool returned in this run."))
            return f"[missing {kind}:{raw}]"
        used.append(record["id"])
        if record.get("kind") not in ("fact", "calc"):
            flags.append(Flag(where, f"{record['id']} is a {record.get('kind')} record, not a number; "
                                     "cite it in citations instead."))
            return f"[not a number: {record['id']}]"
        if record.get("value") is None:
            flags.append(Flag(where, f"{record['id']} has no value: {record.get('reason') or 'unavailable'}"))
            return "unavailable"
        shown = format_value(record)
        word = DIRECTION.search(text, 0, match.start()) if record.get("formula") in CHANGES else None
        value = Decimal(str(record["value"]))
        if word and value:
            if bool(word[1]) == (value < 0):  # the word gives the direction, so show only the size: "fell 3.9 pp"
                return format_value({**record, "value": str(abs(value))}).removeprefix("+")
            flags.append(Flag(where, f"'{word[0].strip()} {shown}' contradicts itself: {record['id']} is {shown}. "
                                     "Fix the direction word, or write 'changed by'."))
        return shown

    filled = PLACEHOLDER.sub(replace, text)
    for number in typed_numbers(text):
        flags.append(Flag(where, f"{number!r} is typed, not a {{fact:ID}}/{{calc:ID}} placeholder, "
                                 "so no tool result backs it."))
    return filled, used, flags


def typed_numbers(text: str) -> list[str]:
    """Figures typed outside placeholders, after removing names like 10-K, Item 1A and years."""
    rest = ALLOWED_NUMBERS.sub(" ", ID_SUFFIX.sub(" ", RECORD_ID.sub(" ", PLACEHOLDER.sub(" ", text))))
    return [m.group().strip() for m in TYPED_NUMBER.finditer(rest)]


def format_value(record: dict) -> str:
    """Deterministic display of a fact or calc value in its unit."""
    value, unit = Decimal(str(record["value"])), record.get("unit")
    if unit == "ratio":
        return f"{_fixed(value * 100)}%"
    if unit == "pp":
        return f"{'+' if value > 0 else ''}{_fixed(value)} pp"
    if unit == "x":
        return f"{_fixed(value)}x"
    if unit == "USD":
        return ("-" if value < 0 else "") + "$" + _scaled(abs(value))
    if unit == "USD/shares":
        return ("-" if value < 0 else "") + f"${_fixed(abs(value), 2)} per share"
    if unit == "shares":
        return f"{_scaled(value)} shares"
    if unit == "insiders":  # get_insider_trades' count of buyers
        return f"{_fixed(value, 0)} insider{'' if value == 1 else 's'}"
    return f"{value} {unit or ''}".strip()


def _scaled(value: Decimal) -> str:
    for size, word in SCALES:
        if abs(value) >= size:
            return f"{_fixed(value / size)} {word}"
    return _fixed(value, 0)


def _fixed(value: Decimal, places: int | None = None) -> str:
    places = config.REPORT_DECIMALS if places is None else places
    return f"{value.quantize(Decimal(1).scaleb(-places), ROUND_HALF_UP):,.{places}f}"
