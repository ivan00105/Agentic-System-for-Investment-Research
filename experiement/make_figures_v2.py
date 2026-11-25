"""Additional figures for the revised report: agent trace timeline (scripted model), eval tool-oracle,
and range informativeness / dev-calibrated widening. All from results/ files."""
import json
from pathlib import Path
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
HERE = Path(__file__).parent; R = HERE / "results"; FIG = HERE.parent / "report" / "figures"
plt.rcParams.update({"font.family": "serif", "font.size": 8, "axes.titlesize": 8.5, "axes.labelsize": 8,
                     "legend.fontsize": 7, "xtick.labelsize": 7, "ytick.labelsize": 7, "axes.spines.top": False,
                     "axes.spines.right": False, "pdf.fonttype": 42})

# 1. Trace timeline of the scripted D run (wrong-period fix)
seq = json.load(open(R / "demo_d_sequence.json"))
lanes = ["host", "coordinator", "fundamentals", "critic"]
style = {"model_call": ("o", "#2166ac", "model call"), "tool_call": ("s", "#4d9221", "tool call"),
         "finish": ("D", "#636363", "finish (typed output)"), "check": ("^", "#e08214", "host checker"),
         "self_review": ("v", "#e08214", "self-review"), "objections": ("X", "#b2182b", "objections"),
         "outcomes": ("P", "#762a83", "outcomes (ledger)"), "plan": ("*", "#2166ac", "plan"),
         "analyst_start": ("|", "#4d9221", "analyst start/end"), "analyst_end": ("|", "#4d9221", None),
         "critic_start": ("|", "#b2182b", None), "revision_start": ("|", "#762a83", None),
         "run_start": ("|", "black", None), "run_end": ("|", "black", None)}
fig, ax = plt.subplots(figsize=(6.6, 1.9))
seen = set()
for i, (kind, role, extra) in enumerate(seq):
    lane = role if role in lanes else "host"
    if kind in ("check", "outcomes"): lane = "host"
    m, c, lab = style.get(kind, (".", "k", None))
    show = lab if lab and lab not in seen else None
    if show: seen.add(lab)
    ax.scatter(i, lanes.index(lane), marker=m, color=c, s=26 if m != "|" else 60, label=show, zorder=3)
    if kind == "tool_call" and extra.startswith("ask_"):
        ax.annotate("", xy=(i, lanes.index("fundamentals")), xytext=(i, lanes.index("coordinator")),
                    arrowprops=dict(arrowstyle="<-", color="#4d9221", lw=0.7))
ax.axvspan(17, 21.5, color="#b2182b", alpha=0.06); ax.text(19.2, 3.42, "critic round 1", ha="center", fontsize=6.5)
ax.axvspan(21.5, 31.5, color="#762a83", alpha=0.06); ax.text(26.5, 3.42, "revision via analyst", ha="center", fontsize=6.5)
ax.axvspan(31.5, 35.5, color="#b2182b", alpha=0.06); ax.text(33.5, 3.42, "round 2", ha="center", fontsize=6.5)
ax.set_yticks(range(len(lanes))); ax.set_yticklabels(lanes); ax.set_ylim(-0.5, 3.75)
ax.set_xlabel("trace event (append-only JSONL, 37 events)"); ax.set_xlim(-1, len(seq))
ax.legend(ncol=5, loc="upper center", bbox_to_anchor=(0.5, -0.42), frameon=False, handletextpad=0.3, columnspacing=0.9)
fig.tight_layout(); fig.savefig(FIG / "agent_trace.pdf", bbox_inches="tight"); plt.close(fig)

# 2. Range informativeness and widening
P = json.load(open(R / "positives_results.json"))
fig, axs = plt.subplots(1, 2, figsize=(6.6, 2.0))
for ax, h in zip(axs, (20, 5)):
    r = P[f"ranges_h{h}"]; t = ["narrow", "middle", "wide"]; x = np.arange(3)
    ax.bar(x - 0.2, [100 * r["tercile_median_width"][k] for k in t], 0.4, color="#9ecae1", label="median predicted width")
    ax.bar(x + 0.2, [100 * r["tercile_median_absmove"][k] for k in t], 0.4, color="#2166ac", label="median realized |deviation|")
    ax2 = ax.twinx(); ax2.plot(x, [100 * r["tercile_coverage"][k] for k in t], "o-", color="#b2182b", ms=3, label="coverage")
    ax2.axhline(80, ls=":", color="#b2182b", lw=0.8); ax2.set_ylim(50, 100); ax2.spines["top"].set_visible(False)
    ax2.set_ylabel("coverage (%)", color="#b2182b")
    ax.set_xticks(x); ax.set_xticklabels([f"{k}\ntercile" for k in t]); ax.set_ylabel("% of price")
    ax.set_title(f"$h={h}$: Spearman(width, |move|) = {r['spearman_width_absmove_2025']:.2f}")
    ax2.spines["right"].set_visible(True)
    if h == 20:
        hs = ax.get_legend_handles_labels(); hs2 = ax2.get_legend_handles_labels()
fig.legend(hs[0] + hs2[0], hs[1] + hs2[1], loc="upper center", ncol=3, frameon=False, fontsize=6.8,
           bbox_to_anchor=(0.5, 1.07), columnspacing=1.2)
fig.tight_layout(); fig.savefig(FIG / "range_informativeness.pdf", bbox_inches="tight"); plt.close(fig)
print("ok")
