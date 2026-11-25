"""Download adjusted daily closes for the evaluation universe and SPY (yfinance, auto-adjusted)."""
import json
from pathlib import Path

import pandas as pd
import yfinance as yf

OUT = Path(__file__).parent / "data"
OUT.mkdir(exist_ok=True)

# 30 liquid US-listed operating companies across sectors; banks and insurers excluded (proposal §4.1).
UNIVERSE = {
    "Information Technology": ["AAPL", "MSFT", "NVDA", "AVGO", "ORCL", "CRM", "ADBE"],
    "Communication Services": ["GOOGL", "META", "NFLX"],
    "Consumer Discretionary": ["AMZN", "HD", "MCD", "NKE"],
    "Consumer Staples": ["PG", "KO", "PEP", "WMT", "COST"],
    "Health Care": ["JNJ", "UNH", "MRK", "ABBV", "PFE"],
    "Energy": ["XOM", "CVX"],
    "Industrials": ["CAT", "HON", "UPS"],
    "Utilities": ["NEE"],
}
TICKERS = [t for group in UNIVERSE.values() for t in group]
assert len(TICKERS) == 30

if __name__ == "__main__":
    data = yf.download(TICKERS + ["SPY"], start="2018-01-01", end="2026-02-28", auto_adjust=True,
                       progress=False, threads=True)
    closes = data["Close"].dropna(how="all")
    closes.to_csv(OUT / "adj_close.csv")
    (OUT / "universe.json").write_text(json.dumps(UNIVERSE, indent=2))
    print(closes.shape, closes.index.min(), closes.index.max())
    print(closes.isna().sum().sort_values().tail(5))
