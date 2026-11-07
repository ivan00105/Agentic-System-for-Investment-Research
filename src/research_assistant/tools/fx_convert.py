"""get_financials' figures in another currency, in US dollars (REFERENCE §5): a year's income and cash flow at that
year's average rate, a balance at the rate on its date. The filed value, the rate and its source stay on the record."""
from datetime import date
from decimal import Decimal

from ..data import fx
from ..data.errors import DataError
from ..finance import currency
from .result import ToolContext, make_id

PLACES = {"USD": Decimal(1), "USD/shares": Decimal("0.0001")}


def to_usd(context: ToolContext, record: dict) -> tuple[dict, fx.Rate]:
    """The fact in US dollars and the rate used; DataError when no provider has a rate for its period."""
    code, per = record["unit"][:3], record["unit"][3:]  # "CNY" and "" or "/shares"
    cache, end = context.cache("fx_cache"), date.fromisoformat(record["end"])
    rate = fx.average(code, date.fromisoformat(record["start"]), end, cache) if record.get("start") \
        else fx.at(code, end, cache)
    outcome = currency.to_usd(Decimal(record["value"]), rate.per_usd)
    if outcome.value is None:
        raise DataError(outcome.reason, "bad_data")
    unit = "USD" + per
    how = (f"the average of {rate.days} daily rates from {rate.first} to {rate.last}" if rate.basis == "average"
           else f"the rate on {rate.last}")
    note = (f"Converted from {record['value']} {record['unit']} at {rate.per_usd} {code} per US dollar, {how} "
            f"({rate.source}{f', series {rate.series}' if rate.series else ''}).")
    converted = {**record, "unit": unit, "value": str(outcome.value.quantize(PLACES[unit])),
                 "reported_value": record["value"], "reported_unit": record["unit"], "fx_rate": str(rate.per_usd),
                 "fx_basis": rate.basis, "fx_first": rate.first.isoformat(), "fx_last": rate.last.isoformat(),
                 "fx_days": rate.days, "fx_source": rate.source, "fx_url": rate.url,
                 "notes": [*record.get("notes", []), note]}
    converted["id"] = make_id("fact", record["id"], unit, rate.per_usd, rate.source)
    return converted, rate
