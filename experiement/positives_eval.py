"""Recheck of the forecasting results: what works, and dev-calibrated fixes (fit on 2024, scored on 2025).
P1  As-shipped direction tool at non-overlapping origins in 2023, 2024 and 2025 (every year reported).
P2  Post-hoc recalibration of the tool's probability, fitted on 2024 origins only: shrinkage toward the
    training base rate (alpha chosen on 2024 Brier) and Platt scaling. Scored on 2025.
P3  Risk ranges: does the predicted width rank realised move sizes (Spearman)? And a dev-calibrated width
    multiplier (fit on 2024 so coverage is 80%) applied unchanged to 2025.
"""
import json, sys
from multiprocessing import Pool
import numpy as np, pandas as pd
from scipy.stats import spearmanr
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score
import outlook_eval as oe
import coverage_eval as ce

def origins(year):
    p0, p1 = oe.pos_of(f"{year}-01-01"), oe.pos_of(f"{year + 1}-01-01")
    return [p for p in range(p0, p1, oe.H) if p + oe.H < len(oe.dates)]

def tool_year(year):
    jobs = [(t, p) for p in origins(year) for t in oe.TICKERS]
    with Pool(2) as pool:
        df = pd.DataFrame(pool.map(oe.shipped_one, jobs))
    return df.dropna(subset=["p_tool"])

def boot_bss(df, col, ref, n=2000, rng=np.random.default_rng(7608)):
    g = [x for _, x in df.groupby("origin")]; v = []
    for _ in range(n):
        s = pd.concat([g[k] for k in rng.integers(0, len(g), len(g))])
        v.append(1 - oe.brier(s[col], s.y) / oe.brier(s[ref], s.y))
    return float(np.percentile(v, 2.5)), float(np.percentile(v, 97.5))

def score(df, col, ref="p_base"):
    b = oe.brier(df[col], df.y); br = oe.brier(df[ref], df.y)
    return {"n": len(df), "brier": b, "bss": 1 - b / br, "ci": boot_bss(df, col, ref),
            "auc": float(roc_auc_score(df.y, df[col])), "sd": float(df[col].std())}

res = {}
years = {y: tool_year(y) for y in (2023, 2024, 2025)}
for y, df in years.items():
    df["p_base"] = df["tool_base_rate"]     # the tool's own per-stock training base rate
    df["p_coin"] = 0.5
    res[f"tool_{y}"] = score(df, "p_tool"); res[f"tool_{y}"]["base_rate_realised"] = float(df.y.mean())
    res[f"tool_{y}"]["brier_coin"] = oe.brier(df.p_coin, df.y); res[f"tool_{y}"]["brier_base"] = oe.brier(df.p_base, df.y)
dev, test = years[2024], years[2025]
# shrinkage toward the tool's own base rate
alphas = np.round(np.arange(0, 1.01, 0.05), 2)
dev_b = {float(a): oe.brier(dev.p_base + a * (dev.p_tool - dev.p_base), dev.y) for a in alphas}
a = min(dev_b, key=dev_b.get)
test["p_shrunk"] = test.p_base + a * (test.p_tool - test.p_base)
res["shrink"] = {"alpha": a, "dev_brier_by_alpha": dev_b, "test": score(test, "p_shrunk")}
# Platt scaling on logit(p_tool)
lg = lambda p: np.log(np.clip(p, 1e-4, 1 - 1e-4) / (1 - np.clip(p, 1e-4, 1 - 1e-4)))
pl = LogisticRegression(C=1.0).fit(lg(dev.p_tool).to_numpy().reshape(-1, 1), dev.y)
test["p_platt"] = pl.predict_proba(lg(test.p_tool).to_numpy().reshape(-1, 1))[:, 1]
res["platt"] = {"coef": float(pl.coef_[0][0]), "intercept": float(pl.intercept_[0]), "test": score(test, "p_platt")}
# reliable_edge gate: does the tool's own diagnostic pick out better forecasts?
for y, df in years.items():
    e = df[df.tool_reliable_edge == True]
    res[f"edge_{y}"] = {"n": int(len(e)), "brier_tool": oe.brier(e.p_tool, e.y) if len(e) else None,
                        "brier_base": oe.brier(e.p_base, e.y) if len(e) else None}

# P3 ranges
def ranges_year(h, year):
    p0, p1 = oe.pos_of(f"{year}-01-01"), oe.pos_of(f"{year + 1}-01-01")
    rows = []
    from datetime import timedelta
    for p in range(p0, p1, 20):
        if p + h >= len(oe.dates): continue
        lo = int(np.searchsorted(oe.dates, oe.dates[p] - timedelta(days=ce.config.OUTLOOK_DEFAULT_LOOKBACK_DAYS)))
        for t in oe.TICKERS:
            s = oe.closes[t].to_numpy()
            o = ce.risk.forecast(s[lo:p + 1].tolist(), oe.spy[lo:p + 1].tolist(), h,
                                 periods_per_year=ce.config.TRADING_DAYS_PER_YEAR,
                                 trailing_threshold=ce.config.OUTLOOK_TRAILING_THRESHOLD,
                                 har_week_days=ce.config.OUTLOOK_HAR_WEEK_DAYS, har_month_days=ce.config.OUTLOOK_HAR_MONTH_DAYS,
                                 min_observations=ce.config.OUTLOOK_MIN_OBSERVATIONS, **ce.KW).value
            rows.append({"ticker": t, "origin": str(oe.dates[p].date()), "low": o.own_low, "high": o.own_high,
                         "actual": s[p + h] / s[p] - 1})
    return pd.DataFrame(rows)
for h in (5, 20):
    d24, d25 = ranges_year(h, 2024), ranges_year(h, 2025)
    for d in (d24, d25):
        d["mid"] = (d.low + d.high) / 2; d["half"] = (d.high - d.low) / 2
        d["width"] = d.high - d.low; d["absdev"] = (d.actual - d.mid).abs()
    def cov(d, k): return float(((d.actual >= d.mid - k * d.half) & (d.actual <= d.mid + k * d.half)).mean())
    ks = np.round(np.arange(0.8, 2.01, 0.01), 2)
    k = float(min((kk for kk in ks if cov(d24, kk) >= 0.80), default=2.0))
    rho, pv = spearmanr(d25.width, d25.absdev)
    # tercile check: realised |move| by predicted-width tercile
    d25["tercile"] = pd.qcut(d25.width, 3, labels=["narrow", "middle", "wide"])
    terc = d25.groupby("tercile", observed=True).agg(width=("width", "median"), absmove=("absdev", "median"),
                                                     coverage=("actual", "size")).to_dict()
    cov_t = {str(t): float(((g.actual >= g.low) & (g.actual <= g.high)).mean()) for t, g in d25.groupby("tercile", observed=True)}
    res[f"ranges_h{h}"] = {"n_2024": len(d24), "n_2025": len(d25), "coverage_2024": cov(d24, 1.0), "coverage_2025": cov(d25, 1.0),
                           "k_dev": k, "coverage_2025_widened": cov(d25, k),
                           "width_2025_median": float(d25.width.median()), "width_2025_widened_median": float((k * d25.width).median()),
                           "spearman_width_absmove_2025": float(rho), "spearman_p": float(pv),
                           "tercile_median_width": {str(a): float(b) for a, b in terc["width"].items()},
                           "tercile_median_absmove": {str(a): float(b) for a, b in terc["absmove"].items()},
                           "tercile_coverage": cov_t}
json.dump(res, open(oe.OUT / "positives_results.json", "w"), indent=1, default=float)
print(json.dumps(res, indent=1, default=float))
