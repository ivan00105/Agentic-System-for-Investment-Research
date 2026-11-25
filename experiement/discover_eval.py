"""Deterministic Discover funnel on the bundled universes: SEC-frames screen, then the host's issuer-level
acceptance recheck (agents/acceptance.py) on the top-ranked candidates. No LLM is involved."""
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1] / "src" / "Agentic-System-for-Investment-Research-main" / "src"
sys.path.insert(0, str(REPO))
from research_assistant.agents.acceptance import Acceptance  # noqa: E402
from research_assistant.agents.trace import Trace  # noqa: E402
from research_assistant.data import universe  # noqa: E402
from research_assistant.data.sec import SecClient  # noqa: E402
from research_assistant.tools import screen  # noqa: E402
from research_assistant.tools.result import ToolContext  # noqa: E402

OUT = Path(__file__).parent / "results"
RECHECK = 10
SCREENS = {
    "S1 tech: op. margin > 25%, revenue growth > 0, rank op. margin": (
        "sp500_tech", [("operating_margin", ">", 0.25), ("revenue_growth", ">", 0.0)], "operating_margin"),
    "S2 S&P 500: FCF margin > 20%, net margin > 15%, rank FCF margin": (
        "sp500", [("fcf_margin", ">", 0.20), ("net_margin", ">", 0.15)], "fcf_margin"),
    "S3 S&P 500: revenue growth > 15%, op. margin > 20%, rank growth": (
        "sp500", [("revenue_growth", ">", 0.15), ("operating_margin", ">", 0.20)], "revenue_growth"),
    "S4 tech: op. margin > 60%, revenue growth > 100% (near-impossible)": (
        "sp500_tech", [("operating_margin", ">", 0.60), ("revenue_growth", ">", 1.0)], "revenue_growth"),
}

if __name__ == "__main__":
    results = {}
    cutoff = datetime(2026, 11, 24, tzinfo=timezone.utc)
    with SecClient() as sec:
        for label, (uni, filters, rank) in SCREENS.items():
            u = universe.load(uni, sec)
            ctx = ToolContext(cutoff=cutoff, sec=sec, cache_dir=Path("/home/user/workspace/rundata"))
            t0 = time.time()
            args = screen.ScreenInput(universe=[m.ticker for m in u.members],
                                      filters=[screen.Filter(metric=m, op=o, value=v) for m, o, v in filters],
                                      rank_by=rank, top_k=RECHECK)
            res = screen.run(args, ctx)
            t_screen = time.time() - t0
            trace = Trace(OUT / "discover_traces" / f"{uni}-{rank}.jsonl", run_id=f"exp-{uni}-{rank}")
            acc = Acceptance(ctx, trace)
            checked = []
            t1 = time.time()
            for c in res.data["candidates"]:
                v = acc.check(c["cik"], c["tickers"], args.filters)
                checked.append({"rank": c["rank"], "name": c["name"], "tickers": c["tickers"],
                                "frame_value": c["values"][rank], "verdict": v.state,
                                "lines": [ln.text for ln in v.lines]})
            t_accept = time.time() - t1
            results[label] = {"universe": uni, "universe_size": len(u.members), "issuers": len(u.ciks),
                              "frame_year": res.data["spec"]["year"], "counts": res.data["counts"],
                              "warnings": res.warnings, "rechecked": checked,
                              "accepted": sum(c["verdict"] == "pass" for c in checked),
                              "rejected": sum(c["verdict"] == "fail" for c in checked),
                              "unknown": sum(c["verdict"] == "unknown" for c in checked),
                              "seconds_screen": round(t_screen, 1), "seconds_acceptance": round(t_accept, 1)}
            print(label, json.dumps({k: results[label][k] for k in ("counts", "accepted", "rejected", "unknown",
                                                                    "seconds_screen", "seconds_acceptance")}))
    (OUT / "discover_results.json").write_text(json.dumps(results, indent=2, default=str))
