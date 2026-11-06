import json
from datetime import datetime, timezone

import httpx
from sec_files import FIXTURES, SecFiles, make_context

from research_assistant.tools.get_financials import GetFinancialsInput, run

APPLE_FACTS = "/api/xbrl/companyfacts/CIK0000320193.json"


def financials(tmp_path, cik="320193", cutoff=None, files=None, **args):
    context = make_context(tmp_path, files=files, **({"cutoff": cutoff} if cutoff else {}))
    return run(GetFinancialsInput(cik=cik, **args), context), context


def values(result, metric):
    return [(v["end"], v["value"]) for v in result.data["metrics"][metric]["values"]]


def test_annual_values_newest_first_from_the_latest_filing(tmp_path):
    result, context = financials(tmp_path, metrics=["revenue", "operating_income"], years=3)
    assert result.status == "ok" and result.source == "SEC companyfacts"
    assert values(result, "revenue") == [("2025-09-27", "416161000000"), ("2024-09-28", "391035000000"),
                                         ("2023-09-30", "383285000000")]
    latest = result.data["metrics"]["revenue"]["values"][0]
    assert (latest["accession"], latest["form"], latest["start"]) == ("0000320193-25-000079", "10-K", "2024-09-29")
    assert context.records[latest["id"]]["metric"] == "revenue" and len(result.ids) == 6


def test_quarterly_10q_values_are_never_annual(tmp_path):
    result, _ = financials(tmp_path, metrics=["revenue"], years=10)
    assert "109417000000" not in [v for _, v in values(result, "revenue")]


def test_cutoff_hides_filings_published_after_it(tmp_path):
    # The FY2025 10-K was filed 2025-10-31, so it is public from 1 November (New York).
    result, _ = financials(tmp_path, metrics=["revenue"], cutoff=datetime(2025, 11, 1, 3, tzinfo=timezone.utc))
    assert values(result, "revenue")[0] == ("2024-09-28", "391035000000")


def test_balance_sheet_values_only_at_fiscal_year_ends(tmp_path):
    result, _ = financials(tmp_path, metrics=["stockholders_equity"], years=2)
    assert values(result, "stockholders_equity") == [("2025-09-27", "73733000000"), ("2024-09-28", "56950000000")]


def test_older_years_are_counted_in_a_warning(tmp_path):
    result, _ = financials(tmp_path, metrics=["revenue"], years=1)
    assert len(values(result, "revenue")) == 1
    assert any("3 older values not shown" in w for w in result.warnings)


def test_restated_value_keeps_the_original(tmp_path):
    payload = json.loads((FIXTURES / "companyfacts_AAPL.json").read_text())
    rows = payload["facts"]["us-gaap"]["RevenueFromContractWithCustomerExcludingAssessedTax"]["units"]["USD"]
    first = next(r for r in rows if r["end"] == "2024-09-28" and r["filed"] == "2024-11-01")
    first["val"] = 390000000000
    result, _ = financials(tmp_path, metrics=["revenue"], files=SecFiles({APPLE_FACTS: httpx.Response(200, json=payload)}))
    fy2024 = result.data["metrics"]["revenue"]["values"][1]
    assert (fy2024["value"], fy2024["original_value"]) == ("391035000000", "390000000000")
    assert any("restated" in w for w in result.warnings)


def test_conflicting_values_in_one_filing_are_withheld_not_fatal(tmp_path):
    payload = json.loads((FIXTURES / "companyfacts_AAPL.json").read_text())
    rows = payload["facts"]["us-gaap"]["RevenueFromContractWithCustomerExcludingAssessedTax"]["units"]["USD"]
    rows.append({**rows[5], "val": 1})
    result, _ = financials(tmp_path, metrics=["revenue"], files=SecFiles({APPLE_FACTS: httpx.Response(200, json=payload)}))
    assert values(result, "revenue")[0][0] == "2024-09-28"
    assert any("conflicting values" in w for w in result.warnings)


def trimmed(cik: int, **tags):
    """A trimmed companyfacts payload; each row is (value, start, end, accession, filed) from a 10-K."""
    rows = {name: {"units": {"USD": [{"start": s, "end": e, "val": v, "accn": a, "form": "10-K", "filed": f}
                                     for v, s, e, a, f in found]}} for name, found in tags.items()}
    files = SecFiles({f"/api/xbrl/companyfacts/CIK{cik:010d}.json": httpx.Response(
        200, json={"cik": cik, "entityName": "Test filer", "facts": {"us-gaap": rows}})})
    return {"cik": str(cik), "files": files}


UDR_2025, UDR_2026 = ("0000074208-25-000009", "2025-02-12"), ("0000074208-26-000013", "2026-02-11")


def test_a_larger_total_replaces_contract_revenue_and_keeps_its_tag(tmp_path):
    # UDR, a REIT: ASC 606 contract revenue leaves out lease income. FY2025 values are real, FY2024 synthetic.
    filer = trimmed(74208, RevenueFromContractWithCustomerExcludingAssessedTax=[
        (10964000, "2024-01-01", "2024-12-31", *UDR_2025), (10964000, "2024-01-01", "2024-12-31", *UDR_2026),
        (11361000, "2025-01-01", "2025-12-31", *UDR_2026)], Revenues=[
        (1670000000, "2024-01-01", "2024-12-31", *UDR_2026), (1712317000, "2025-01-01", "2025-12-31", *UDR_2026)])
    result, _ = financials(tmp_path, metrics=["revenue"], **filer)
    latest, prior = result.data["metrics"]["revenue"]["values"]
    assert (latest["value"], latest["tag"], latest["accession"]) == ("1712317000", "us-gaap:Revenues", UDR_2026[0])
    # The earlier 10-K tagged only contract revenue: another tag, not a restatement.
    assert (prior["value"], prior["tag"], prior.get("original_value")) == ("1670000000", "us-gaap:Revenues", None)
    assert not any("restated" in w for w in result.warnings)


def test_sales_including_excise_tax_never_replace_net_sales(tmp_path):
    # Brown-Forman: the tax-inclusive figure is contract revenue too, so the tax-exclusive one stays.
    filing = ("0000014693-26-000021", "2026-06-12")
    filer = trimmed(14693, RevenueFromContractWithCustomerExcludingAssessedTax=[
        (3928000000, "2025-05-01", "2026-04-30", *filing)], RevenueFromContractWithCustomerIncludingAssessedTax=[
        (5082000000, "2025-05-01", "2026-04-30", *filing)])
    result, _ = financials(tmp_path, metrics=["revenue"], **filer)
    assert [(v["value"], v["tag"]) for v in result.data["metrics"]["revenue"]["values"]] == [
        ("3928000000", "us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax")]


def test_a_conflicting_total_is_withheld_not_swapped_for_contract_revenue(tmp_path):
    filer = trimmed(74208, RevenueFromContractWithCustomerExcludingAssessedTax=[
        (10964000, "2024-01-01", "2024-12-31", *UDR_2025), (11361000, "2025-01-01", "2025-12-31", *UDR_2026)], Revenues=[
        (1712317000, "2025-01-01", "2025-12-31", *UDR_2026), (1500000000, "2025-01-01", "2025-12-31", *UDR_2026)])
    result, _ = financials(tmp_path, metrics=["revenue"], **filer)
    assert values(result, "revenue") == [("2024-12-31", "10964000")]
    assert any("2025-12-31 has conflicting values" in w for w in result.warnings)


def test_bank_operating_income_is_unsupported_but_revenue_works(tmp_path):
    result, _ = financials(tmp_path, cik="19617", metrics=["revenue", "operating_income"])
    assert result.status == "partial"
    assert result.data["metrics"]["operating_income"]["status"] == "unsupported"
    assert values(result, "revenue")[0][0] == "2025-12-31"


def test_ifrs_filer_is_unsupported(tmp_path):
    result, _ = financials(tmp_path, cik="1046179")
    assert result.status == "unsupported" and "IFRS" in result.warnings[0]


def test_missing_metric_is_not_reported_with_the_tags_tried(tmp_path):
    result, _ = financials(tmp_path, metrics=["gross_profit"])
    assert result.status == "not_found"
    assert "us-gaap:GrossProfit" in result.data["metrics"]["gross_profit"]["reason"]


def foreign_variant(unit):
    """Apple's facts reshaped like a foreign filer's US GAAP 20-F, reported in `unit`."""
    payload = json.loads((FIXTURES / "companyfacts_AAPL.json").read_text())
    concept = payload["facts"]["us-gaap"]["RevenueFromContractWithCustomerExcludingAssessedTax"]
    rows = concept["units"].pop("USD")
    for row in rows:
        row["form"] = "20-F" if row["form"] == "10-K" else row["form"]
    concept["units"][unit] = rows
    return SecFiles({APPLE_FACTS: httpx.Response(200, json=payload)})


def test_us_gaap_20f_in_dollars_is_supported(tmp_path):
    result, _ = financials(tmp_path, metrics=["revenue"], files=foreign_variant("USD"))
    assert result.status == "ok" and result.data["metrics"]["revenue"]["values"][0]["form"] == "20-F"


def test_other_currency_is_unsupported_and_named(tmp_path):
    result, _ = financials(tmp_path, metrics=["revenue"], files=foreign_variant("CNY"))
    assert result.status == "unsupported"
    assert result.data["metrics"]["revenue"]["reason"].startswith("Reported in CNY, not USD")


def test_dollar_values_next_to_another_currency_are_flagged(tmp_path):
    payload = json.loads((FIXTURES / "companyfacts_AAPL.json").read_text())
    units = payload["facts"]["us-gaap"]["RevenueFromContractWithCustomerExcludingAssessedTax"]["units"]
    units["CNY"] = [{**row, "val": row["val"] * 7} for row in units["USD"]]
    result, _ = financials(tmp_path, metrics=["revenue"], files=SecFiles({APPLE_FACTS: httpx.Response(200, json=payload)}))
    assert result.status == "ok" and any("convenience translations" in w for w in result.warnings)


def test_quarter_and_off_year_end_rows_inside_a_10k_are_ignored(tmp_path):
    payload = json.loads((FIXTURES / "companyfacts_AAPL.json").read_text())
    gaap = payload["facts"]["us-gaap"]
    annual = gaap["RevenueFromContractWithCustomerExcludingAssessedTax"]["units"]["USD"][5]
    gaap["RevenueFromContractWithCustomerExcludingAssessedTax"]["units"]["USD"].append(
        {**annual, "start": "2025-06-29", "val": 102466000000})  # a fourth quarter in the same 10-K
    equity = gaap["StockholdersEquity"]["units"]["USD"]
    equity.append({**equity[-2], "end": "2025-06-28", "val": 1})  # a balance between fiscal year ends
    files = SecFiles({APPLE_FACTS: httpx.Response(200, json=payload)})
    result, _ = financials(tmp_path, metrics=["revenue", "stockholders_equity"], files=files, years=10)
    assert "102466000000" not in [v for _, v in values(result, "revenue")]
    assert "2025-06-28" not in [end for end, _ in values(result, "stockholders_equity")]


def test_a_total_from_an_older_filing_does_not_override_the_latest_one(tmp_path):
    # Second review: the latest filing tags only contract revenue for FY2024; the older total is not swapped in.
    filer = trimmed(74208, RevenueFromContractWithCustomerExcludingAssessedTax=[
        (10964000, "2024-01-01", "2024-12-31", *UDR_2025), (10964000, "2024-01-01", "2024-12-31", *UDR_2026)], Revenues=[
        (1670000000, "2024-01-01", "2024-12-31", *UDR_2025)])
    result, _ = financials(tmp_path, metrics=["revenue"], **filer)
    assert values(result, "revenue") == [("2024-12-31", "10964000")]
    assert ("revenue for the period ending 2024-12-31: a larger us-gaap:Revenues total (1670000000) is in filing "
            f"{UDR_2025[0]}, not the latest {UDR_2026[0]}; the latest filing's value is kept.") in result.warnings
