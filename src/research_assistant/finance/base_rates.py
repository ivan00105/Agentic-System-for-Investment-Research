"""Outside-view business forecasts from as-filed annual SEC observations."""
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from statistics import quantiles


FULL_YEAR_DAYS = (330, 380)  # as data/sec_facts.py: a 10-K also tags quarters
NEXT_YEAR_DAYS = (350, 380)  # between two fiscal year ends, 52/53-week years included


@dataclass(frozen=True)
class CompanyYear:
    cik: str
    end: date
    revenue: Decimal
    operating_margin: Decimal | None


def _full_year(row: dict) -> bool:
    try:
        days = (date.fromisoformat(row["end"]) - date.fromisoformat(row["start"])).days
    except (KeyError, TypeError, ValueError):
        return False
    return FULL_YEAR_DAYS[0] <= days <= FULL_YEAR_DAYS[1]


def first_reported(rows: list[dict], cutoff: str | None = None) -> list[dict]:
    """The earliest filed full-year value per fiscal year end; quarters and later restatements never replace it."""
    chosen: dict[str, dict] = {}
    for row in rows:
        if cutoff and row.get("filed", "") > cutoff:
            continue
        if row.get("form") not in {"10-K", "10-K/A", "20-F", "20-F/A", "40-F", "40-F/A"}:
            continue
        if not _full_year(row):
            continue
        key = row["end"]
        if key not in chosen or (row.get("filed", ""), row.get("accession", "")) < (
            chosen[key].get("filed", ""), chosen[key].get("accession", "")):
            chosen[key] = row
    return list(chosen.values())


def observations(cik: str, revenue_rows: list[dict], operating_rows: list[dict],
                 revenue_floor: Decimal = Decimal(0), cutoff: str | None = None) -> list[CompanyYear]:
    revenue = {r["end"]: r for r in first_reported(revenue_rows, cutoff)}
    operating = {r["end"]: r for r in first_reported(operating_rows, cutoff)}
    result = []
    for end, row in revenue.items():
        value = Decimal(str(row["value"]))
        if value < revenue_floor:
            continue
        margin = None
        if end in operating and Decimal(str(operating[end]["value"])) is not None:
            margin = Decimal(str(operating[end]["value"])) / value if value > 0 else None
        result.append(CompanyYear(cik, date.fromisoformat(end), value, margin))
    return sorted(result, key=lambda item: item.end)


def next_year_changes(years: list[CompanyYear]) -> list[dict]:
    changes = []
    for current, following in zip(years, years[1:], strict=False):
        gap = (following.end - current.end).days
        if not NEXT_YEAR_DAYS[0] <= gap <= NEXT_YEAR_DAYS[1] or current.revenue <= 0:
            continue
        growth = (following.revenue - current.revenue) / current.revenue
        margin_change = None
        if current.operating_margin is not None and following.operating_margin is not None:
            margin_change = following.operating_margin - current.operating_margin
        changes.append({"cik": current.cik, "year": current.end.year, "growth": growth, "margin_change": margin_change})
    return changes


def spread(values: list[Decimal]) -> dict[str, Decimal | None]:
    if not values:
        return {"p10": None, "p50": None, "p90": None}
    if len(values) == 1:
        return {"p10": values[0], "p50": values[0], "p90": values[0]}
    q = quantiles(values, n=10, method="inclusive")
    return {"p10": q[0], "p50": q[4], "p90": q[8]}


def chance_above(values: list[Decimal], thresholds: list[Decimal]) -> dict[str, Decimal | None]:
    n = len(values)
    return {str(threshold): (sum(value > threshold for value in values) / n if n else None)
            for threshold in thresholds}


def forecast(samples: list[dict], thresholds: list[Decimal]) -> dict:
    growth = [row["growth"] for row in samples]
    margin = [row["margin_change"] for row in samples if row["margin_change"] is not None]
    return {
        "observations": len(samples),
        "growth": spread(growth),
        "growth_chance_above": chance_above(growth, thresholds),
        "margin_change": spread(margin),
        "margin_observations": len(margin),
        "sample_ciks": sorted({row["cik"] for row in samples}),
    }
