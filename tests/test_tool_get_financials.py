import json
from datetime import datetime, timezone

from decimal import Decimal

import httpx
import pytest
from fx_rates import Frankfurter
from sec_files import FIXTURES, SecFiles, make_context

from research_assistant.data import fx_frankfurter
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


def test_a_20f_share_count_comes_with_the_ads_ratio_from_its_cover(tmp_path):
    result, context = financials(tmp_path, cik="1577552", metrics=["shares_outstanding"], years=1)
    shares = result.data["metrics"]["shares_outstanding"]["values"][0]
    ratio = result.data["metrics"]["ordinary_shares_per_ads"]["values"][0]
    assert ratio["value"] == "8" and ratio["accession"] == shares["accession"] == "0001193125-26-231755"
    assert ratio["tag"] == "dei:Security12bTitle" and "each representing eight Ordinary Shares" in ratio["notes"][0]
    assert ratio["id"] in result.ids and context.records[ratio["id"]]["unit"] == "shares/ADS"


def test_a_cover_count_the_tag_cuts_off_uses_the_printed_number(tmp_path):
    # BABA's 2026 cover tags "18,580,374,27" and prints the last 8 after the tag, so companyfacts has 1,858,037,427.
    result, context = financials(tmp_path, cik="1577552", metrics=["shares_outstanding"], years=1)
    shares = result.data["metrics"]["shares_outstanding"]["values"][0]
    assert shares["value"] == "18580374278" and shares["tagged_value"] == "1858037427"
    assert context.records[shares["id"]]["value"] == "18580374278" and shares["id"] in result.ids
    assert any("cuts the number off" in w for w in result.warnings)


def test_a_direct_listing_is_one_ordinary_share_per_listed_share(tmp_path):
    result, _ = financials(tmp_path, cik="1015922", metrics=["shares_outstanding"], years=1)
    ratio = result.data["metrics"]["ordinary_shares_per_ads"]["values"][0]
    assert ratio["value"] == "1" and ratio["tag"] == "no depositary shares"
    assert result.data["metrics"]["shares_outstanding"]["values"][0]["value"] == "105596035"


def test_a_ratio_whose_filing_is_missing_is_unsupported_not_fatal(tmp_path):
    empty = {"cik": "1577552", "filings": {"recent": {}, "files": []}}
    files = SecFiles({"/submissions/CIK0001577552.json": httpx.Response(200, json=empty)})
    result, _ = financials(tmp_path, cik="1577552", metrics=["shares_outstanding"], years=1, files=files)
    ratio = result.data["metrics"]["ordinary_shares_per_ads"]
    assert result.status == "partial" and ratio["status"] == "unsupported" and "not in SEC's list" in ratio["reason"]
    assert result.data["metrics"]["shares_outstanding"]["values"][0]["value"] == "1858037427"  # cover unread: as filed


def test_a_10k_share_count_needs_no_ads_ratio(tmp_path):
    result, _ = financials(tmp_path, metrics=["shares_outstanding"])
    assert "ordinary_shares_per_ads" not in result.data["metrics"]


@pytest.fixture
def ecb(monkeypatch):
    mock = Frankfurter()
    monkeypatch.setattr(fx_frankfurter, "transport", httpx.MockTransport(mock))
    return mock


def test_figures_in_another_currency_convert_at_the_years_average_and_year_end_rates(tmp_path, ecb):
    result, context = financials(tmp_path, cik="1577552", metrics=["revenue", "total_assets", "eps_diluted"], years=2)
    revenue = result.data["metrics"]["revenue"]
    assert revenue["unit"] == "USD" and [(v["end"], v["fx_rate"]) for v in revenue["values"]] == [
        ("2026-03-31", "7.200000"), ("2025-03-31", "7.000000")]
    latest = revenue["values"][0]
    assert latest["value"] == str((Decimal(1023670000000) / Decimal("7.2")).quantize(Decimal(1)))
    assert (latest["reported_value"], latest["reported_unit"], latest["fx_basis"]) == ("1023670000000", "CNY", "average")
    assert latest["fx_first"] == "2025-04-01" and latest["fx_last"] == "2026-03-31"
    assert "at 7.200000 CNY per US dollar, the average of" in latest["notes"][0]
    assert context.records[latest["id"]]["unit"] == "USD" and latest["id"] in result.ids
    assets = result.data["metrics"]["total_assets"]["values"][0]
    assert assets["fx_basis"] == "year_end" and assets["fx_last"] == "2026-03-31"
    eps = result.data["metrics"]["eps_diluted"]["values"][0]
    assert context.records[eps["id"]]["unit"] == "USD/shares" and eps["value"] == "0.7639"  # 5.50 CNY / 7.2
    assert result.source == "SEC companyfacts; exchange rates: Frankfurter (ECB reference rates) (fallback)"
    assert any(w.startswith("Converted to USD from CNY at Frankfurter") for w in result.warnings)
    assert any("FRED_API_KEY" in w for w in result.warnings)
    assert not any("convenience translations at one exchange rate per filing" in w for w in result.warnings)


def test_without_a_rate_the_filings_own_dollars_are_shown_and_say_so(tmp_path):
    result, _ = financials(tmp_path, cik="1577552", metrics=["revenue"], years=1)  # tests block Frankfurter
    assert values(result, "revenue") == [("2026-03-31", "148401000000")]
    assert any(w.startswith("revenue: no CNY exchange rate") for w in result.warnings)
    assert any("convenience translations" in w for w in result.warnings)


def test_a_filer_reporting_only_another_currency_converts_when_a_rate_exists(tmp_path, ecb):
    result, _ = financials(tmp_path, metrics=["revenue"], years=1, files=foreign_variant("CNY"))
    (latest,) = result.data["metrics"]["revenue"]["values"]
    assert result.status == "ok" and latest["reported_unit"] == "CNY"
    assert Decimal("7.0") < Decimal(latest["fx_rate"]) < Decimal("7.2")  # the year spans the mocked change of rate
