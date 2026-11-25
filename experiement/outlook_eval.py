"""Leakage-safe evaluation of Fieldnote's 20-session direction forecast and 80% risk ranges.

E1  As-shipped tool: quant.direction_forecast exactly as get_outlook calls it (3-year lookback, repo config),
    issued at non-overlapping 2025 origins and scored on realised outcomes.
E2  Leakage-safe pooled logistic on the same five features: fit/scale on 2021-2023 (purged), tune C on 2024,
    refit on 2021-2024 (purged), test on 2025. Baselines: coin (0.5), training base rate.
E3  Risk ranges: risk.walk_forward_coverage (repo code) for 5- and 20-session own-return 80% intervals.
"""
import json
import sys
from datetime import timedelta
from multiprocessing import Pool
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score
from sklearn.preprocessing import StandardScaler

REPO = Path(__file__).resolve().parents[1] / "src" / "Agentic-System-for-Investment-Research-main" / "src"
sys.path.insert(0, str(REPO))
from research_assistant import config  # noqa: E402
from research_assistant.finance import quant, risk  # noqa: E402

HERE = Path(__file__).parent
OUT = HERE / "results"
OUT.mkdir(exist_ok=True)
H = 20
RNG = np.random.default_rng(7608)

closes = pd.read_csv(HERE / "data" / "adj_close.csv", index_col=0, parse_dates=True)
UNIVERSE = json.loads((HERE / "data" / "universe.json").read_text())
TICKERS = [t for g in UNIVERSE.values() for t in g]
dates = closes.index
spy = closes["SPY"].to_numpy()


# ---------- features identical to quant.direction_forecast ----------
def features(stock: np.ndarray, bench: np.ndarray) -> pd.DataFrame:
    n = len(stock)
    rows = np.full((n, 5), np.nan)
    label = np.full(n, np.nan)
    for i in range(60, n):
        sr = stock[i] / stock[i - 60] - 1
        br = bench[i] / bench[i - 60] - 1
        short = stock[i] / stock[i - 5] - bench[i] / bench[i - 5]
        rec = stock[i - 20:i] / stock[i - 21:i - 1] - bench[i - 20:i] / bench[i - 21:i - 1]
        vol = rec.std()
        ma = stock[i - 20:i].mean()
        rows[i] = [sr - br, short, sr - br, vol, stock[i] / ma - 1]
        if i + H < n:
            fwd = stock[i + H] / stock[i] - bench[i + H] / bench[i]
            label[i] = 1.0 if fwd > 0 else 0.0
    df = pd.DataFrame(rows, index=dates, columns=["rel60", "rel5", "mom60", "vol20", "ma20"])
    df["y"] = label
    return df


def panel() -> pd.DataFrame:
    parts = []
    for t in TICKERS:
        f = features(closes[t].to_numpy(), spy)
        f["ticker"] = t
        f["pos"] = np.arange(len(f))
        parts.append(f)
    return pd.concat(parts).dropna(subset=["rel60"])


def pos_of(day: str) -> int:
    return int(np.searchsorted(dates, pd.Timestamp(day)))


P_TRAIN0, P_DEV0, P_TEST0, P_END = pos_of("2021-01-01"), pos_of("2024-01-01"), pos_of("2025-01-01"), pos_of("2026-01-01")


def brier(p, y):
    return float(np.mean((np.asarray(p) - np.asarray(y)) ** 2))


def grouped_bootstrap(df: pd.DataFrame, cols: list[str], ref: str, n=2000):
    """Resample forecast origins (dates), not stock-dates: stocks share market shocks."""
    groups = [g for _, g in df.groupby("origin")]
    out = {c: [] for c in cols}
    for _ in range(n):
        pick = RNG.integers(0, len(groups), len(groups))
        s = pd.concat([groups[k] for k in pick])
        b_ref = brier(s[ref], s["y"])
        for c in cols:
            out[c].append(1 - brier(s[c], s["y"]) / b_ref if b_ref else np.nan)
    return {c: (float(np.nanpercentile(v, 2.5)), float(np.nanpercentile(v, 97.5))) for c, v in out.items()}


def leakage_safe(pn: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    feats = ["rel60", "rel5", "vol20", "ma20"]  # mom60 duplicates rel60 exactly; dropped for identifiability
    train = pn[(pn.pos >= P_TRAIN0) & (pn.pos < P_DEV0 - H)]          # purge: labels resolve before dev starts
    dev = pn[(pn.pos >= P_DEV0) & (pn.pos < P_TEST0 - H)]
    test = pn[(pn.pos >= P_TEST0) & (pn.pos < P_END) & pn.y.notna()]
    grid = [1e-4, 1e-3, 1e-2, 1e-1, 1.0, 10.0]
    tune = {}
    for c in grid:
        sc = StandardScaler().fit(train[feats])
        m = LogisticRegression(C=c, max_iter=2000).fit(sc.transform(train[feats]), train.y)
        tune[c] = brier(m.predict_proba(sc.transform(dev[feats]))[:, 1], dev.y)
    best = min(tune, key=tune.get)
    fit = pn[(pn.pos >= P_TRAIN0) & (pn.pos < P_TEST0 - H)]
    sc = StandardScaler().fit(fit[feats])
    m = LogisticRegression(C=best, max_iter=2000).fit(sc.transform(fit[feats]), fit.y)
    test = test.copy()
    test["p_logit"] = m.predict_proba(sc.transform(test[feats]))[:, 1]
    test["p_base"] = float(fit.y.mean())
    test["p_coin"] = 0.5
    meta = {"C_grid_dev_brier": {str(k): v for k, v in tune.items()}, "C_best": best,
            "train_rows": int(len(train)), "dev_rows": int(len(dev)), "fit_rows": int(len(fit)),
            "test_rows": int(len(test)), "train_base_rate": float(train.y.mean()),
            "fit_base_rate": float(fit.y.mean()), "test_base_rate": float(test.y.mean()),
            "coef": dict(zip(feats, map(float, m.coef_[0]))), "intercept": float(m.intercept_[0])}
    return test, meta


# ---------- E1: as-shipped tool ----------
def shipped_one(args):
    ticker, origin_pos = args
    day = dates[origin_pos]
    start = day - timedelta(days=config.OUTLOOK_DEFAULT_LOOKBACK_DAYS)
    lo = int(np.searchsorted(dates, start))
    s = closes[ticker].to_numpy()[lo:origin_pos + 1].tolist()
    b = spy[lo:origin_pos + 1].tolist()
    o = quant.direction_forecast(s, b, H, min_observations=config.DIRECTION_MIN_OBSERVATIONS,
                                 regularization=config.DIRECTION_REGULARIZATION,
                                 learning_rate=config.DIRECTION_LEARNING_RATE,
                                 max_iterations=config.DIRECTION_MAX_ITERATIONS)
    v = o.value
    full = closes[ticker].to_numpy()
    y = 1.0 if full[origin_pos + H] / full[origin_pos] - spy[origin_pos + H] / spy[origin_pos] > 0 else 0.0
    return {"ticker": ticker, "origin": str(day.date()), "pos": origin_pos, "y": y,
            "p_tool": v.probability if v else None, "tool_base_rate": v.base_rate if v else None,
            "tool_auc_diag": v.auc if v else None, "tool_bss_diag": v.brier_skill if v else None,
            "tool_reliable_edge": v.reliable_edge if v else None}


def summarise(df: pd.DataFrame, cols: list[str], ref: str = "p_base") -> dict:
    res = {}
    b_ref = brier(df[ref], df.y)
    for c in cols:
        b = brier(df[c], df.y)
        res[c] = {"n": int(len(df)), "brier": b, "bss_vs_" + ref: 1 - b / b_ref,
                  "auc": float(roc_auc_score(df.y, df[c])) if df[c].nunique() > 1 else None,
                  "accuracy": float(np.mean((df[c] > 0.5) == (df.y == 1)))}
    return res


def calibration(df: pd.DataFrame, col: str, bins=(0, .4, .45, .5, .55, .6, 1.0)):
    cut = pd.cut(df[col], bins, include_lowest=True)
    g = df.groupby(cut, observed=True).agg(n=("y", "size"), mean_p=(col, "mean"), freq=("y", "mean"))
    return [{"bin": str(k), **{kk: float(vv) for kk, vv in r.items()}} for k, r in g.iterrows()]


def coverage_study():
    out = {}
    for h in (5, 20):
        per_year, total, covered, scores = {}, 0, 0, []
        for t in TICKERS:
            sub = closes.loc[: "2025-12-31"]
            ds = [d.strftime("%Y-%m-%d") for d in sub.index]
            o = risk.walk_forward_coverage(ds, sub[t].tolist(), sub["SPY"].tolist(), h,
                                           quantile_low=config.OUTLOOK_QUANTILE_LOW,
                                           quantile_high=config.OUTLOOK_QUANTILE_HIGH,
                                           conformal_coverage=config.OUTLOOK_CONFORMAL_COVERAGE,
                                           conformal_learning_rate=config.OUTLOOK_CONFORMAL_LEARNING_RATE,
                                           min_training_observations=config.OUTLOOK_MIN_OBSERVATIONS)
            v = o.value
            total += v.observations
            covered += v.covered
            scores.append(v.interval_score)
            for y, (n, c, _) in v.by_year.items():
                a = per_year.setdefault(y, [0, 0])
                a[0] += n
                a[1] += c
        out[h] = {"observations": total, "covered": covered, "coverage": covered / total,
                  "mean_interval_score": float(np.mean(scores)),
                  "by_year": {y: {"n": n, "covered": c, "coverage": c / n} for y, (n, c) in sorted(per_year.items())}}
    return out


if __name__ == "__main__":
    pn = panel()
    test, meta = leakage_safe(pn)
    # Non-overlapping origins: every 20th session from the first 2025 session.
    origins = list(range(P_TEST0, P_END, H))
    origins = [p for p in origins if p + H < len(dates)]
    jobs = [(t, p) for p in origins for t in TICKERS]
    with Pool(2) as pool:
        shipped = pd.DataFrame(pool.map(shipped_one, jobs, chunksize=4))
    shipped.to_csv(OUT / "shipped_tool_forecasts.csv", index=False)

    # Join leakage-safe predictions onto the same non-overlapping origins.
    key = test.set_index(["ticker", "pos"])
    shipped["p_logit"] = [key.loc[(t, p), "p_logit"] for t, p in zip(shipped.ticker, shipped.pos)]
    shipped["p_base"] = meta["fit_base_rate"]
    shipped["p_coin"] = 0.5
    shipped["y_check"] = [key.loc[(t, p), "y"] for t, p in zip(shipped.ticker, shipped.pos)]
    assert (shipped.y == shipped.y_check).all()
    ok = shipped.dropna(subset=["p_tool"])
    cols = ["p_coin", "p_base", "p_logit", "p_tool"]
    nonoverlap = summarise(ok, cols)
    nonoverlap_ci = grouped_bootstrap(ok, ["p_logit", "p_tool"], "p_base")

    test = test.copy()
    test["origin"] = test.index.astype(str)
    daily = summarise(test, ["p_coin", "p_base", "p_logit"])
    daily_ci = grouped_bootstrap(test, ["p_logit"], "p_base", n=1000)

    # The proposal's replay grid: 10 non-overlapping origins x 10 fixed companies.
    ten = ["AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "JNJ", "PG", "XOM", "CAT", "WMT"]
    grid = ok[ok.ticker.isin(ten) & ok.origin.isin(sorted(ok.origin.unique())[:10])]
    proposal_grid = summarise(grid, cols)

    diag = {"tool_auc_diag_mean": float(ok.tool_auc_diag.mean()), "tool_bss_diag_mean": float(ok.tool_bss_diag.mean()),
            "tool_reliable_edge_share": float(ok.tool_reliable_edge.mean()),
            "tool_prob_mean": float(ok.p_tool.mean()), "tool_prob_sd": float(ok.p_tool.std()),
            "tool_prob_min": float(ok.p_tool.min()), "tool_prob_max": float(ok.p_tool.max()),
            "logit_prob_sd": float(test.p_logit.std()), "logit_prob_min": float(test.p_logit.min()),
            "logit_prob_max": float(test.p_logit.max())}

    by_origin = ok.groupby("origin").apply(lambda g: pd.Series({"n": len(g), "outperform_rate": g.y.mean(),
        "brier_tool": brier(g.p_tool, g.y), "brier_base": brier(g.p_base, g.y), "brier_logit": brier(g.p_logit, g.y)}),
        include_groups=False)
    by_origin.to_csv(OUT / "by_origin.csv")

    coverage = coverage_study()
    results = {"meta": meta, "origins": [str(dates[p].date()) for p in origins],
               "non_overlapping": nonoverlap, "non_overlapping_bss_ci": nonoverlap_ci,
               "daily_test": daily, "daily_test_bss_ci": daily_ci, "proposal_grid_10x10": proposal_grid,
               "tool_diagnostics": diag, "calibration_logit_daily": calibration(test, "p_logit"),
               "calibration_tool": calibration(ok, "p_tool"), "risk_coverage": coverage,
               "issued": int(len(shipped)), "abstained": int(shipped.p_tool.isna().sum())}
    (OUT / "outlook_results.json").write_text(json.dumps(results, indent=2))
    test[["ticker", "origin", "y", "p_logit", "p_base"]].to_csv(OUT / "logit_daily_test.csv", index=False)
    print(json.dumps(results, indent=2))
