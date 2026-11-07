"""Currency conversion (no I/O). A rate is units of the other currency per US dollar, as FRED and ECB quote it."""
from decimal import Decimal

from . import Outcome

RATE_PLACES = Decimal("0.000001")


def mean(rates: list[Decimal]) -> Decimal:
    """The average of daily rates, to six decimals (FRED quotes four)."""
    return (sum(rates) / len(rates)).quantize(RATE_PLACES)


def to_usd(amount: Decimal, per_usd: Decimal) -> Outcome:
    if per_usd <= 0:
        return Outcome(None, "An exchange rate must be positive.")
    return Outcome(amount / per_usd)
