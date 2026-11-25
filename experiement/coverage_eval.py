"""Corrected interval-coverage checks for the Outlook's nominal 80% ranges.

C1  As-shipped: risk.forecast exactly as get_outlook calls it (3-year lookback, repo config), issued at the 13
    non-overlapping 2025 origins for each of the 30 stocks; scored on the realised h-session own return.
C2  Corrected yearly walk-forward: same interval construction as risk.walk_forward_coverage, but each test year
    stops at the year's last session whose h-session window ends inside the data (the repo loop runs to the end
    of the series, so its 'by_year' buckets overlap and double-count).
"""
import json
import sys
from datetime import timedelta
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[1] / "src" / "Agentic-System-for-Investment-Research-main" / "src"
sys.path.insert(0, str(REPO))
from research_assistant import config  # noqa: E402
from research_assistant.finance import risk  # noqa: E402

HERE = Path(__file__).parent
closes = pd.read_csv(HERE / "data" / "adj_close.csv", index_col=0, parse_dates=True)
UNIVERSE = json.loads((HERE / "data" / "universe.json").read_text())
TICKERS = [t for g in UNIVERSE.values() for t in g]
dates = closes.index
spy = closes["SPY"].to_numpy()
KW = dict(quantile_low=config.OUTLOOK_QUANTILE_LOW, quantile_high=config.OUTLOOK_QUANTILE_HIGH,
          conformal_coverage=config.OUTLOOK_CONFORMAL_COVERAGE,
          conformal_learning_rate=config.OUTLOOK_CONFORMAL_LEARNING_RATE)


def shipped(h: int):
    p0, p1 = int(np.searchsorted(dates, pd.Timestamp("2025-01-01"))), int(np.searchsorted(dates, pd.Timestamp("2026-01-01")))
    rows = []
    for p in range(p0, p1, 20):
        if p + h >= len(dates):
            continue
        lo = int(np.searchsorted(dates, dates[p] - timedelta(days=config.OUTLOOK_DEFAULT_LOOKBACK_DAYS)))
        for t in TICKERS:
            s = closes[t].to_numpy()
            o = risk.forecast(s[lo:p + 1].tolist(), spy[lo:p + 1].tolist(), h,
                              periods_per_year=config.TRADING_DAYS_PER_YEAR,
                              trailing_threshold=config.OUTLOOK_TRAILING_THRESHOLD,
                              har_week_days=config.OUTLOOK_HAR_WEEK_DAYS, har_month_days=config.OUTLOOK_HAR_MONTH_DAYS,
                              min_observations=config.OUTLOOK_MIN_OBSERVATIONS, **KW).value
            actual = s[p + h] / s[p] - 1
            rel = actual - (spy[p + h] / spy[p] - 1)
            rows.append({"ticker": t, "origin": str(dates[p].date()), "low": o.own_low, "high": o.own_high,
                         "actual": actual, "covered": o.own_low <= actual <= o.own_high,
                         "rel_low": o.relative_low, "rel_high": o.relative_high, "rel": rel,
                         "rel_covered": o.relative_low <= rel <= o.relative_high,
                         "trail_p": o.trail_probability, "trailed10": rel <= config.OUTLOOK_TRAILING_THRESHOLD})
    df = pd.DataFrame(rows)
    cov = risk.coverage_tests(df.covered.tolist(), 0.80).value
    by_origin = df.groupby("origin").covered.mean()
    trail_brier = float(np.mean((df.trail_p - df.trailed10.astype(float)) ** 2))
    return df, {"n": len(df), "covered": int(df.covered.sum()), "coverage": float(df.covered.mean()),
                "relative_coverage": float(df.rel_covered.mean()),
                "median_width": float((df.high - df.low).median()),
                "kupiec_p_value_naive": cov.kupiec_p_value,
                "origin_coverage_min": float(by_origin.min()), "origin_coverage_max": float(by_origin.max()),
                "trail10_mean_p": float(df.trail_p.mean()), "trail10_freq": float(df.trailed10.mean()),
                "trail10_brier": trail_brier,
                "trail10_brier_base": float(np.mean((df.trailed10.mean() - df.trailed10) ** 2))}


def corrected_walk_forward(h: int):
    ds = [d.strftime("%Y-%m-%d") for d in dates]
    years = [str(y) for y in range(2019, 2026)]
    out = {}
    for y in years:
        n = c = 0
        for t in TICKERS:
            s = closes[t].to_numpy()
            start = next(i for i, d in enumerate(ds) if d[:4] == y)
            end = max(i for i, d in enumerate(ds) if d[:4] == y)
            own, _ = risk._forward_returns(s[:start].tolist(), spy[:start].tolist(), h)
            low, high, _ = risk._conformal_interval(own, risk._quantile(own, KW["quantile_low"]),
                                                    risk._quantile(own, KW["quantile_high"]),
                                                    coverage=KW["conformal_coverage"],
                                                    learning_rate=KW["conformal_learning_rate"])
            for i in range(start, min(end + 1, len(s) - h)):
                a = s[i + h] / s[i] - 1
                n += 1
                c += int(low <= a <= high)
        out[y] = {"n": n, "covered": c, "coverage": c / n}
    return out


if __name__ == "__main__":
    res = {}
    for h in (5, 20):
        df, summary = shipped(h)
        df.to_csv(HERE / "results" / f"shipped_ranges_h{h}.csv", index=False)
        res[f"shipped_h{h}"] = summary
        res[f"corrected_walk_forward_h{h}"] = corrected_walk_forward(h)
    (HERE / "results" / "coverage_results.json").write_text(json.dumps(res, indent=2))
    print(json.dumps(res, indent=2))
