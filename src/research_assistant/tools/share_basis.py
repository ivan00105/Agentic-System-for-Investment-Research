"""A 20-F or 40-F share count's basis (REFERENCE §5): how many ordinary shares one ADS stands for, as a citable
fact read from the same filing (its cover, else its text), and the share count as that cover page shows it."""
from decimal import Decimal
from fractions import Fraction

from ..data import sec_cover, sec_filings
from ..data.errors import DataError
from ..data.sec_facts import available_at
from .result import ToolContext, make_id

FOREIGN_FORMS = {"20-F", "20-F/A", "40-F", "40-F/A"}
METRIC = "ordinary_shares_per_ads"
UNIT = "shares/ADS"
HIDDEN = ("kind", "cik", "metric", "unit", "source_url")  # as get_financials lists its values


def _digits(text: str) -> str:
    return text.replace(",", "")


def _fix_cut_count(context: ToolContext, value: dict, cover: dict, ids: list[str], warnings: list[str]) -> None:
    """A cover whose one tagged count stops short of the printed number (BABA's 2026 20-F) gets the printed number."""
    shown = cover["shares"][0]["shown"] if len(cover["shares"]) == 1 else None
    if not shown or Decimal(_digits(cover["shares"][0]["tagged"])) != Decimal(value["value"]):
        return
    old = context.records.pop(value["id"])
    note = (f"The cover's inline XBRL tag holds \"{cover['shares'][0]['tagged']}\" ({old['value']} in companyfacts) "
            f"but the page shows {shown}: the tag cuts the number off, so the page's count is used.")
    record = {**old, "id": make_id("fact", old["cik"], old["tag"], old["end"], old["accession"], _digits(shown), "page"),
              "value": _digits(shown), "tagged_value": old["value"], "notes": [*old.get("notes", []), note]}
    ids[ids.index(old["id"])] = context.remember(record)
    value.update({k: v for k, v in record.items() if k not in HIDDEN})
    warnings.append(f"shares_outstanding at {old['end']}: {note}")


def _record(cik: str, filing, cover: dict) -> dict:
    value = Fraction(cover["ratio"])
    if cover["how"] == "no depositary shares":
        note = f"The cover lists no depositary shares ({cover['basis']}), so one US-listed share is one ordinary share."
    elif cover["how"] == sec_cover.FILING_TEXT:
        note = (f"The cover gives no ratio, so it is read from the filing's text, the only ratio it states: "
                f"\"{cover['basis']}\".")
    else:
        where = "inline XBRL title" if cover["how"] == sec_cover.TITLE_TAG else "Section 12(b) table"
        note = f"Read from the cover's {where}: \"{cover['basis']}\"."
    return {"id": make_id("fact", cik, METRIC, filing.accession, cover["ratio"]), "kind": "fact", "cik": cik,
            "metric": METRIC, "tag": cover["how"], "unit": UNIT,
            "value": str(Decimal(value.numerator) / Decimal(value.denominator)), "start": None,
            "end": (filing.report_date or filing.filed).isoformat(), "accession": filing.accession, "form": filing.form,
            "filed": filing.filed.isoformat(), "available_at": available_at(filing.filed).isoformat(),
            "source_url": filing.url, "filing_url": filing.folder_url, "title": cover["basis"], "notes": [note]}


def add(context: ToolContext, cik: str, metrics: dict, ids: list[str], warnings: list[str]) -> None:
    """Puts `ordinary_shares_per_ads` next to a 20-F/40-F share count, one fact per filing the counts come from."""
    foreign = [v for v in metrics.get("shares_outstanding", {}).get("values", []) if v.get("form") in FOREIGN_FORMS]
    if not foreign:
        return
    values, problems = [], []
    for accession in dict.fromkeys(v["accession"] for v in foreign):
        try:
            filing = sec_filings.find(context.sec, cik, accession)
            if filing is None:
                raise DataError(f"filing {accession} is not in SEC's list.", "not_found")
            cover = sec_cover.read(context.sec, filing, context.cache("ixbrl_cache"))
        except DataError as exc:
            problems.append(f"{accession}: {exc}")
            continue
        for value in (v for v in foreign if v["accession"] == accession):
            _fix_cut_count(context, value, cover, ids, warnings)
        if cover["ratio"] is None:
            problems.append(f"{accession}: {cover['problem']}")
            continue
        record = _record(cik, filing, cover)
        ids.append(context.remember(record))
        values.append({k: v for k, v in record.items() if k not in HIDDEN})
    if values:
        metrics[METRIC] = {"status": "ok", "unit": UNIT, "values": values}
        warnings += [f"{METRIC} unsupported for {p}" for p in problems]
    else:
        metrics[METRIC] = {"status": "unsupported", "reason": "Ordinary shares per ADS unsupported: " + " ".join(problems)}
