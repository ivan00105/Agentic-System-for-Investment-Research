"""Margins, growth, cash flow and valuation on Decimals (formulas follow FinanceToolkit, with the
zero and negative denominator guards it lacks; REFERENCE §10)."""
from decimal import Decimal, localcontext

from . import Outcome


def _divide(a: Decimal, b: Decimal) -> Decimal:
    with localcontext() as context:
        context.prec = 28
        return a / b


def ratio(numerator: Decimal, denominator: Decimal, what: str = "ratio") -> Outcome:
    if denominator <= 0:
        return Outcome(None, f"{what} is not meaningful with a zero or negative denominator ({denominator}).")
    return Outcome(_divide(numerator, denominator))


def growth(current: Decimal, previous: Decimal) -> Outcome:
    if previous <= 0:
        return Outcome(None, f"Growth from a zero or negative base ({previous}) is not meaningful.")
    return Outcome(_divide(current - previous, previous))


def change_pp(current: Decimal, previous: Decimal) -> Outcome:
    """Change between two ratios in percentage points: 10% -> 12% is +2 pp, not +20%."""
    return Outcome((current - previous) * 100)


def cagr(first: Decimal, last: Decimal, years: Decimal) -> Outcome:
    if years <= 0:
        return Outcome(None, "CAGR needs a later end value than start value.")
    if first <= 0 or last <= 0:
        return Outcome(None, "CAGR is not meaningful when either end is zero or negative.")
    with localcontext() as context:
        context.prec = 28
        return Outcome(_divide(last, first) ** (Decimal(1) / years) - 1)


def free_cash_flow(operating_cash_flow: Decimal, capex: Decimal) -> Outcome:
    note = "Free cash flow is non-GAAP: operating cash flow minus capital expenditure."
    if capex < 0:
        note += f" Capex was reported as a negative number ({capex}); it was treated as cash spent."
    return Outcome(operating_cash_flow - abs(capex), note=note)


def market_cap(price: Decimal, shares: Decimal) -> Outcome:
    if price <= 0 or shares <= 0:
        return Outcome(None, "Market cap needs a positive price and share count.")
    return Outcome(price * shares)


def multiple(market_cap: Decimal, denominator: Decimal, what: str) -> Outcome:
    """P/E, P/S, P/B: not meaningful when the denominator is zero or negative (losses, negative equity)."""
    return ratio(market_cap, denominator, what)


def enterprise_value(market_cap: Decimal, debt: Decimal, cash: Decimal) -> Outcome:
    return Outcome(market_cap + debt - cash, note="Enterprise value = market cap + debt - cash; leases are not included.")
