"""Figures for the report, all from measured results in results/."""
import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

HERE = Path(__file__).parent
R = HERE / "results"
FIG = HERE.parent / "report" / "figures"
FIG.mkdir(parents=True, exist_ok=True)
plt.rcParams.update({"font.family": "serif", "font.size": 8, "axes.titlesize": 8.5, "axes.labelsize": 8,
                     "legend.fontsize": 7, "xtick.labelsize": 7, "ytick.labelsize": 7, "axes.spines.top": False,
                     "axes.spines.right": False, "pdf.fonttype": 42})
C_TOOL, C_LOGIT, C_BASE = "#b2182b", "#2166ac", "#636363"

out = json.loads((R / "outlook_results.json").read_text())
tool = pd.read_csv(R / "shipped_tool_forecasts.csv")
logit = pd.read_csv(R / "logit_daily_test.csv")
logit["origin"] = logit.origin.str[:10]
tool = tool.merge(logit[["ticker", "origin", "p_logit"]], on=["ticker", "origin"], how="left")
assert tool.p_logit.notna().all()
by_origin = pd.read_csv(R / "by_origin.csv")


def reliability(ax, p, y, bins, color, label, marker):
    cut = pd.cut(p, bins, include_lowest=True)
    g = pd.DataFrame({"p": p, "y": y}).groupby(cut, observed=True).agg(mp=("p", "mean"), fy=("y", "mean"), n=("y", "size"))
    se = np.sqrt(g.fy * (1 - g.fy) / g.n)
    ax.errorbar(g.mp, g.fy, yerr=1.96 * se, color=color, marker=marker, ms=3.5, lw=1, capsize=1.5, label=label)


# ---- Figure: direction forecast reliability + Brier by origin ----
fig, axes = plt.subplots(1, 3, figsize=(6.6, 2.05), gridspec_kw={"width_ratios": [1, 1, 1.35]})
ax = axes[0]
bins = [0, .3, .4, .45, .5, .55, .6, .7, 1]
ax.plot([0, 1], [0, 1], ls=":", color="k", lw=0.8)
reliability(ax, tool.p_tool, tool.y, bins, C_TOOL, "Shipped tool (n=390)", "o")
reliability(ax, logit.p_logit, logit.y, [0, .45, .48, .5, .52, .55, .6, 1], C_LOGIT, "Leakage-safe logit (n=7,500)", "s")
ax.axhline(out["meta"]["test_base_rate"], color=C_BASE, lw=0.8, ls="--", label="2025 base rate")
ax.set_xlim(0, 1); ax.set_ylim(0, 1)
ax.set_xlabel("Forecast probability"); ax.set_ylabel("Observed outperformance rate")
ax.set_title("(a) Reliability, 2025 test"); ax.legend(loc="upper left", frameon=True, framealpha=1, edgecolor="none", fontsize=5.8, borderpad=0.2, handlelength=1.6)

ax = axes[1]
ax.hist(tool.p_tool, bins=np.linspace(0, 1, 26), color=C_TOOL, alpha=0.75, label="Shipped tool")
ax.hist(tool.p_logit, bins=np.linspace(0, 1, 26), color=C_LOGIT, alpha=0.6, label="Leakage-safe logit")
ax.set_xlabel("Forecast probability"); ax.set_ylabel("Forecasts (same 390 cases)")
ax.set_title("(b) Sharpness"); ax.legend(frameon=False, fontsize=6.2)

ax = axes[2]
x = pd.to_datetime(by_origin.origin)
ax.plot(x, by_origin.brier_tool, marker="o", ms=3, color=C_TOOL, lw=1, label="Shipped tool")
ax.plot(x, by_origin.brier_logit, marker="s", ms=3, color=C_LOGIT, lw=1, label="Leakage-safe logit")
ax.plot(x, by_origin.brier_base, marker="^", ms=3, color=C_BASE, lw=1, label="Base rate")
ax.axhline(0.25, color="k", lw=0.6, ls=":")
ax.set_ylabel("Brier score (30 stocks)"); ax.set_title("(c) Brier score by origin")
ax.tick_params(axis="x", rotation=40)
ax.xaxis.set_major_formatter(matplotlib.dates.DateFormatter("%b"))
ax.set_ylim(0.19, 0.32)
ax.legend(frameon=False, fontsize=6.0, loc="lower right", ncol=1, handlelength=1.4)
fig.tight_layout(pad=0.4, w_pad=0.9)
fig.savefig(FIG / "direction_forecast.pdf"); plt.close(fig)

# ---- Figure: interval coverage ----
cov = json.loads((R / "coverage_results.json").read_text())
fig, ax = plt.subplots(figsize=(3.3, 2.0))
years = sorted(cov["corrected_walk_forward_h5"])
w = 0.38
xs = np.arange(len(years))
ax.bar(xs - w / 2, [cov["corrected_walk_forward_h5"][y]["coverage"] for y in years], w, color="#92c5de", label="5 sessions")
ax.bar(xs + w / 2, [cov["corrected_walk_forward_h20"][y]["coverage"] for y in years], w, color="#2166ac", label="20 sessions")
ax.axhline(0.80, color="k", ls="--", lw=0.8, label="nominal 80%")
ax.set_xticks(xs, years); ax.set_ylim(0, 1.2); ax.set_ylabel("Empirical coverage")
ax.set_title("Out-of-sample coverage of 80% return ranges")
ax.legend(frameon=False, loc="upper center", ncol=3, fontsize=6.3, columnspacing=0.8)
fig.tight_layout(pad=0.3)
fig.savefig(FIG / "interval_coverage.pdf"); plt.close(fig)

# ---- Figure: Discover funnel ----
d = json.loads((R / "discover_results.json").read_text())
labels = ["S1", "S2", "S3", "S4"]
rows = list(d.values())
fig, ax = plt.subplots(figsize=(3.3, 2.0))
xs = np.arange(4)
screened = [r["counts"]["screened"] for r in rows]
failed = [r["counts"]["failed"] for r in rows]
unknown = [r["counts"]["unknown"] for r in rows]
eligible = [r["counts"]["eligible"] for r in rows]
ax.bar(xs, failed, color="#d6604d", label="fail")
ax.bar(xs, unknown, bottom=failed, color="#bababa", label="unknown")
ax.bar(xs, eligible, bottom=np.add(failed, unknown), color="#4393c3", label="eligible (pass)")
for i, r in enumerate(rows):
    ax.text(i, screened[i] + 8, f"{r['accepted']}/{len(r['rechecked'])}", ha="center", fontsize=6.5)
ax.set_xticks(xs, labels); ax.set_ylabel("Issuers screened"); ax.set_ylim(0, 640)
ax.set_title("Discover funnel (accepted / rechecked)")
ax.legend(frameon=False, fontsize=6.3, loc="upper center", ncol=3, columnspacing=0.8)
fig.tight_layout(pad=0.3)
fig.savefig(FIG / "discover_funnel.pdf"); plt.close(fig)
print("figures written to", FIG)
