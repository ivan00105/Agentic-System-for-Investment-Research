"""Yahoo Finance prices through yfinance (tier 0: no key). Unofficial and rate-limited by IP, so results are cached.

Yahoo's Close is already split-adjusted, so the as-traded close is rebuilt from the full split history
(REFERENCE §5). yfinance is imported on first use: it pulls in pandas.
"""
import warnings
from datetime import date, timedelta

from .errors import DataError

NAME, TIER, ENV, LABEL = "yfinance", 0, (), "Yahoo Finance (yfinance)"


def configured() -> bool:
    return True


def _history(ticker: str, start: date, end: date):
    # yfinance turns its own pandas deprecation notices back on at import; they say nothing about the data
    # and bury the agent's progress lines, so they stay inside this block.
    with warnings.catch_warnings():
        import yfinance  # first: its import puts a "default" filter ahead of any set earlier

        warnings.simplefilter("ignore", DeprecationWarning)

        handle = yfinance.Ticker(ticker)
        # yfinance's end date is exclusive.
        frame = handle.history(start=start.isoformat(), end=(end + timedelta(days=1)).isoformat(), auto_adjust=False,
                               actions=True, raise_errors=False)
        return frame, handle.splits


def to_rows(frame, splits) -> list[dict]:
    """Rows with the as-traded close: Yahoo's split-adjusted Close times every split after that day."""
    split_list = [(index.date(), float(ratio)) for index, ratio in splits.items() if ratio and ratio != 1]
    rows = []
    for index, row in frame.iterrows():
        day = index.date()
        factor = 1.0
        for split_day, ratio in split_list:
            if split_day > day:
                factor *= ratio
        rows.append({"date": day.isoformat(), "close": round(float(row["Close"]) * factor, 6),
                     "adj_close": float(row["Adj Close"]), "volume": float(row["Volume"]),
                     "dividend": float(row.get("Dividends", 0.0)), "split": float(row.get("Stock Splits", 0.0)) or 1.0})
    return rows


def fetch(ticker: str, start: date, end: date) -> list[dict]:
    try:
        frame, splits = _history(ticker, start, end)
    except Exception as exc:  # yfinance raises many unrelated types for network and parsing failures
        raise DataError(f"yfinance failed: {exc}", "network") from exc
    if frame is None or frame.empty:
        raise DataError(f"Yahoo has no prices for {ticker} between {start} and {end}.", "not_found")
    return to_rows(frame, splits)


def check() -> str:
    fetch("SPY", date.today() - timedelta(days=10), date.today())
    return "Yahoo Finance returned prices for SPY."
