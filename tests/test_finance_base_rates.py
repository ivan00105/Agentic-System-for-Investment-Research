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
