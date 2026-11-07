"""sec_facts.reporting_unit: the currency of the newest annual filing public at the cutoff (REFERENCE §5)."""
from datetime import datetime, timezone

from research_assistant.data import sec_facts

REVENUE = sec_facts.CONCEPTS["revenue"]
OLD_20F, NEW_20F = ("0000000042-24-000001", "2024-04-30"), ("0000000042-25-000001", "2025-04-30")
NOW = datetime(2026, 11, 8, tzinfo=timezone.utc)


def revenue(*rows) -> dict:
    """A 20-F filer's companyfacts; each row is (unit, value, fiscal year, (accession, filed))."""
    units = {}
    for unit, value, year, (accession, filed) in rows:
        units.setdefault(unit, []).append({"start": f"{year}-01-01", "end": f"{year}-12-31", "val": value,
                                           "accn": accession, "form": "20-F", "filed": filed})
    return {"facts": {"us-gaap": {"Revenues": {"units": units}}}}


def chosen(payload: dict, cutoff: datetime) -> tuple[str, list[tuple[str, str]]]:
    """The unit used, and each period's value in it, as get_financials picks them."""
    unit = sec_facts.reporting_unit(payload, REVENUE, cutoff)
    facts, _ = sec_facts.select(payload, REVENUE, cutoff, sec_facts.fiscal_year_ends(payload, cutoff), unit)
    return unit, [(f.end.isoformat(), str(f.value)) for f in facts]


def test_a_currency_filed_after_the_cutoff_does_not_change_a_historical_query():
    payload = revenue(("USD", 100, 2023, OLD_20F), ("USD", 90, 2022, OLD_20F),
                      *[("CNY", value, year, NEW_20F) for year, value in ((2024, 800), (2023, 700), (2022, 630))])
    past = datetime(2024, 12, 31, tzinfo=timezone.utc)
    assert chosen(payload, past) == ("USD", [("2023-12-31", "100"), ("2022-12-31", "90")])
    assert chosen(payload, NOW)[0] == "CNY"  # once public, the CNY 20-F is the newest


def test_another_currency_is_named_only_once_its_filing_is_public():
    payload = revenue(("USD", 100, 2023, OLD_20F), ("CNY", 700, 2023, NEW_20F))
    assert sec_facts.other_units(payload, REVENUE, datetime(2024, 12, 31, tzinfo=timezone.utc)) == []
    assert sec_facts.other_units(payload, REVENUE, NOW) == ["CNY"]


def test_a_switch_of_reporting_currency_keeps_the_newest_year():
    payload = revenue(*[("CNY", value, year, OLD_20F) for year, value in ((2023, 700), (2022, 630), (2021, 560))],
                      ("USD", 110, 2024, NEW_20F), ("USD", 100, 2023, NEW_20F))
    assert chosen(payload, NOW) == ("USD", [("2024-12-31", "110"), ("2023-12-31", "100")])
