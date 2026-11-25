from decimal import Decimal

from research_assistant.finance import base_rates, fundamentals
from research_assistant.tools.get_base_rates import GetBaseRatesInput, run
from sec_files import make_context


class _Response:
    def __init__(self, payload):
        self.payload = payload

    def json(self):
        return self.payload


def test_first_reported_ignores_a_later_restatement():
    rows = [
        {"start": "2022-01-01", "end": "2022-12-31", "filed": "2023-02-01", "accession": "a",
         "form": "10-K", "value": "100"},
        {"start": "2022-01-01", "end": "2022-12-31", "filed": "2024-02-01", "accession": "b",
         "form": "10-K", "value": "120"},
    ]
    assert base_rates.first_reported(rows)[0]["value"] == "100"


def test_forecast_spread_and_threshold():
    samples = [{"cik": "1", "growth": Decimal("0.1"), "margin_change": Decimal("0.01")},
               {"cik": "2", "growth": Decimal("0.2"), "margin_change": Decimal("0.02")}]
    result = base_rates.forecast(samples, [Decimal("0.15")])
    assert result["observations"] == 2
    assert result["growth"]["p50"] == Decimal("0.15")
    assert result["growth_chance_above"]["0.15"] == 0.5


def test_implied_growth_reverses_the_dcf():
    result = fundamentals.implied_growth(Decimal("1000"), Decimal("1000"), Decimal(".1"), Decimal(".5"),
                                         Decimal(".1"), Decimal(".02"), 10)
    assert result.value is not None
    assert Decimal("-0.99") < result.value < Decimal("2")


def test_base_rate_tool_keeps_first_reported_values(tmp_path):
    def rows(values):
        return [{"start": f"{year}-01-01", "end": f"{year}-12-31", "filed": f"{year + 1}-02-01",
                 "accession": f"a{year}", "form": "10-K", "val": str(value)}
                for year, value in values]
    payload = {"facts": {"us-gaap": {
        "RevenueFromContractWithCustomerExcludingAssessedTax": {"units": {"USD": rows([(2021, 100), (2022, 120)])}},
        "OperatingIncomeLoss": {"units": {"USD": rows([(2021, 10), (2022, 12)])}},
    }}}
    context = make_context(tmp_path)
    context.sec.companyfacts = lambda cik: _Response(payload)
    result = run(GetBaseRatesInput(cik="1", revenue_floor=Decimal(1)), context)
    assert result.status == "ok" and result.data["first_reported"] is True
    assert result.data["observations"] == 1


def _row(start, end, value, filed="2023-02-01", form="10-K"):
    return {"start": start, "end": end, "filed": filed, "form": form, "value": str(value), "val": str(value)}


def test_a_quarter_in_the_10k_never_replaces_the_full_year():
    rows = [_row("2022-01-01", "2022-12-31", 1000), _row("2022-10-01", "2022-12-31", 260)]
    for order in (rows, rows[::-1]):
        assert [item.revenue for item in base_rates.observations("1", order, [])] == [Decimal(1000)]


def test_52_53_week_years_pair_with_the_next_fiscal_year():
    # As Johnson & Johnson: two fiscal years end in calendar 2022.
    rows = [_row("2020-01-04", "2021-01-02", 100), _row("2021-01-03", "2022-01-01", 110),
            _row("2022-01-02", "2022-12-31", 132)]
    changes = base_rates.next_year_changes(base_rates.observations("1", rows, []))
    assert [item["growth"] for item in changes] == [Decimal("0.1"), Decimal("0.2")]


def test_a_missing_year_is_not_bridged():
    rows = [_row("2020-01-01", "2020-12-31", 100), _row("2022-01-01", "2022-12-31", 130)]
    assert base_rates.next_year_changes(base_rates.observations("1", rows, [])) == []


def test_base_rate_tool_says_what_its_sample_is(tmp_path):
    payload = {"facts": {"us-gaap": {"Revenues": {"units": {"USD": [
        _row("2021-01-01", "2021-12-31", 100, "2022-02-01"), _row("2022-01-01", "2022-12-31", 120)]}}}}}
    context = make_context(tmp_path)
    context.sec.companyfacts = lambda cik: _Response(payload)
    alone = run(GetBaseRatesInput(cik="1", revenue_floor=Decimal(1)), context)
    assert alone.data["sample"] == "the company's own history" and "not an outside view" in alone.warnings[0]
    assert "survivorship_free_input" not in alone.data
    compared = run(GetBaseRatesInput(cik="1", comparable_ciks=["2"], revenue_floor=Decimal(1)), context)
    assert compared.data["sample"] == "the companies passed in" and compared.warnings == []
