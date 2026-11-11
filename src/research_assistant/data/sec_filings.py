"""Filing lists from SEC submissions JSON, including the older pages in `files[]` (REFERENCE §10).

A filing counts from its acceptance time (UTC in the JSON), so the cutoff is exact to the second.
Forms that SEC releases later than it dates them (`RELEASED_LATER`) never count.
"""
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Iterator

from .sec import SecClient, cik10
from .sec_facts import available_at

# Form 8-K item codes (https://www.sec.gov/files/form8-k.pdf).
EIGHT_K_ITEMS = {
    "1.01": "Entry into a material definitive agreement", "1.02": "Termination of a material definitive agreement",
    "1.03": "Bankruptcy or receivership", "1.04": "Mine safety", "1.05": "Material cybersecurity incident",
    "2.01": "Completed acquisition or disposition of assets", "2.02": "Results of operations and financial condition",
    "2.03": "New direct financial obligation", "2.04": "Event accelerating a financial obligation",
    "2.05": "Exit or disposal costs", "2.06": "Material impairment",
    "3.01": "Delisting or failure to meet a listing rule", "3.02": "Unregistered sale of equity securities",
    "3.03": "Material change to security holders' rights", "4.01": "Change of auditor",
    "4.02": "Previously issued financial statements can no longer be relied on", "5.01": "Change in control",
    "5.02": "Director or officer departure, election or pay", "5.03": "Charter or bylaw amendment; fiscal year change",
    "5.04": "Suspension of trading in employee benefit plans", "5.05": "Code of ethics change or waiver",
    "5.06": "Change in shell company status", "5.07": "Shareholder vote results", "5.08": "Shareholder director nominations",
    "6.01": "ABS informational material", "6.02": "Change of ABS servicer or trustee", "6.03": "Change in ABS credit enhancement",
    "6.04": "Failure to make an ABS distribution", "6.05": "ABS securities act updating disclosure",
    "6.06": "Static pool", "7.01": "Regulation FD disclosure", "8.01": "Other events", "9.01": "Financial statements and exhibits",
}

# SEC puts these on EDGAR long after the date it gives them, and its data has no release date (REFERENCE §5):
# confidential drafts (DRS; Regulation A's DOS), their cover letters, and review letters to and from SEC staff.
RELEASED_LATER = frozenset({"DRS", "DRS/A", "DRSLTR", "DOS", "DOS/A", "DOSLTR", "CORRESP", "UPLOAD"})
RELEASED_LATER_WHY = ("SEC publishes these forms (drafts and review letters) later than the date it shows, "
                      "and that release date is not in its data")


@dataclass(frozen=True)
class Filing:
    cik: str
    accession: str
    form: str
    filed: date
    accepted_at: datetime | None
    report_date: date | None  # 8-K: the event date; 10-K/10-Q: the period end
    items: tuple[str, ...]
    primary_document: str
    description: str

    @property
    def folder_url(self) -> str:
        return f"https://www.sec.gov/Archives/edgar/data/{int(self.cik)}/{self.accession.replace('-', '')}/"

    @property
    def url(self) -> str:
        return self.folder_url + self.primary_document

    def public_by(self, cutoff: datetime) -> bool:
        return self.form not in RELEASED_LATER and (self.accepted_at or available_at(self.filed)) <= cutoff


def _cell(columns: dict, name: str, i: int, default=""):
    values = columns.get(name, [])
    return values[i] if i < len(values) and values[i] is not None else default


def _parse(cik: str, columns: dict) -> list[Filing]:
    filings = []
    for i, accession in enumerate(columns.get("accessionNumber", [])):
        try:
            accepted = _cell(columns, "acceptanceDateTime", i)
            report = _cell(columns, "reportDate", i)
            filings.append(Filing(
                cik, accession, _cell(columns, "form", i), date.fromisoformat(_cell(columns, "filingDate", i)),
                datetime.fromisoformat(accepted).astimezone(timezone.utc) if accepted else None,
                date.fromisoformat(report) if report else None,
                tuple(code.strip() for code in _cell(columns, "items", i).split(",") if code.strip()),
                _cell(columns, "primaryDocument", i), _cell(columns, "primaryDocDescription", i)))
        except ValueError:
            continue  # one malformed row must not hide the rest
    return filings


def pages(sec: SecClient, cik: int | str, since: date | None = None) -> Iterator[list[Filing]]:
    """Newest filings first: the recent block, then each older page only when the caller asks for more.
    Pages that end before `since` are never fetched."""
    cik = cik10(cik)
    payload = sec.submissions(cik).json()
    yield _parse(cik, payload.get("filings", {}).get("recent", {}))
    older = sorted(payload.get("filings", {}).get("files", []), key=lambda f: f.get("filingTo", ""), reverse=True)
    for page in older:
        if since and page.get("filingTo", "9999") < since.isoformat():
            return
        yield _parse(cik, sec.get(f"https://data.sec.gov/submissions/{page['name']}").json())


def search(sec: SecClient, cik: int | str, cutoff: datetime, *, forms: set[str] | None = None, since: date | None = None,
           after: tuple[date, str] | None = None, limit: int | None = None) -> list[Filing]:
    """Filings public at the cutoff, newest first; stops reading pages once `limit` are found or `since` is passed.

    `after` is the (filing date, accession) of the last filing already shown: paging continues right after it,
    so other filings from that same day are never skipped."""
    found: list[Filing] = []
    for page in pages(sec, cik, since):
        for filing in sorted(page, key=lambda f: (f.filed, f.accession), reverse=True):
            if since and filing.filed < since:
                return found
            if (filing.public_by(cutoff) and (not forms or filing.form in forms)
                    and (not after or (filing.filed, filing.accession) < after)):
                found.append(filing)
                if limit is not None and len(found) >= limit:
                    return found
    return found


def find(sec: SecClient, cik: int | str, accession: str) -> Filing | None:
    for page in pages(sec, cik):
        for filing in page:
            if filing.accession == accession:
                return filing
    return None
