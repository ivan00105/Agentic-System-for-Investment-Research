"""yfinance earnings, dividend and option-chain fallback (tier 0: no key)."""
import warnings
from datetime import date

import pandas as pd

NAME, TIER, ENV, LABEL = "yfinance", 0, (), "Yahoo Finance (yfinance)"


def configured() -> bool:
    return True


def _earnings_dates(ticker: str):
    with warnings.catch_warnings():
        import yfinance
        warnings.simplefilter("ignore", DeprecationWarning)
        return yfinance.Ticker(ticker).earnings_dates


def _dividends(ticker: str):
    with warnings.catch_warnings():
        import yfinance
        warnings.simplefilter("ignore", DeprecationWarning)
        return yfinance.Ticker(ticker).dividends


def fetch(ticker: str, start: date, end: date) -> list[dict]:
    rows = []
    try:
        earnings = _earnings_dates(ticker)
        if earnings is not None:
            for index, row in earnings.iterrows():
                day = index.date() if hasattr(index, "date") else pd.Timestamp(index).date()
                if start <= day <= end:
                    rows.append({"kind": "earnings", "date": day.isoformat(),
                                 "status": "occurred" if day < date.today() else "upcoming",
                                 "details": {"eps_estimate": str(row.get("EPS Estimate"))}
                                 if row.get("EPS Estimate") is not None else {}, "source": "yfinance"})
    except Exception:
        pass
    try:
        dividends = _dividends(ticker)
        if dividends is not None:
            for index, amount in dividends.items():
                day = index.date() if hasattr(index, "date") else pd.Timestamp(index).date()
                if start <= day <= end:
                    rows.append({"kind": "ex_dividend", "date": day.isoformat(),
                                 "status": "occurred" if day < date.today() else "upcoming",
                                 "details": {"amount": str(amount)}, "source": "yfinance"})
    except Exception:
        pass
    if not rows:
        raise Exception("Yahoo returned no earnings or ex-dividend dates.")
    return rows


def _option_snapshot(ticker: str, expiry: str) -> dict:
    import yfinance
    handle = yfinance.Ticker(ticker)
    spot = float(getattr(getattr(handle, "fast_info", None), "last_price", 0.0) or 0.0)
    chain = handle.option_chain(expiry)
    calls = chain.calls.to_dict("records")
    puts = chain.puts.to_dict("records")
    if not spot:
        raise ValueError("No live spot price")
    return {"spot": spot, "calls": calls, "puts": puts}


def option_expiries(ticker: str) -> list[str]:
    import yfinance
    return list(yfinance.Ticker(ticker).options or [])


def check() -> str:
    if not option_expiries("SPY"):
        raise RuntimeError("Yahoo returned no option expiries for SPY.")
    return "Yahoo Finance returned live option expiries."
