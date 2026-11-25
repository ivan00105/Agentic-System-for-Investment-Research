"""S2 rerun with Financials (and, separately, Financials + Real Estate) removed from the universe before screening:
the sector-exclusion fix proposed in the defects table, measured without changing repository code."""
import json, sys, time
from datetime import datetime, timezone
from pathlib import Path
REPO = Path(__file__).resolve().parents[1] / "src" / "Agentic-System-for-Investment-Research-main" / "src"
sys.path.insert(0, str(REPO))
from research_assistant.agents.acceptance import Acceptance
from research_assistant.agents.trace import Trace
from research_assistant.data import universe
from research_assistant.data.sec import SecClient
from research_assistant.tools import screen
from research_assistant.tools.result import ToolContext
OUT = Path(__file__).parent / "results"
filters = [("fcf_margin", ">", 0.20), ("net_margin", ">", 0.15)]
res_all = {}
cutoff = datetime(2026, 11, 24, tzinfo=timezone.utc)
with SecClient() as sec:
    u = universe.load("sp500", sec)
    for label, excl in {"ex_financials": {"Financials"}, "ex_financials_real_estate": {"Financials", "Real Estate"}}.items():
        members = [m for m in u.members if (m.sector or "") not in excl]
        ctx = ToolContext(cutoff=cutoff, sec=sec, cache_dir=Path("/home/user/workspace/rundata"))
        args = screen.ScreenInput(universe=[m.ticker for m in members],
                                  filters=[screen.Filter(metric=m, op=o, value=v) for m, o, v in filters],
                                  rank_by="fcf_margin", top_k=10)
        t0 = time.time(); res = screen.run(args, ctx); ts = time.time() - t0
        acc = Acceptance(ctx, Trace(OUT / "discover_traces" / f"s2-{label}.jsonl", run_id=f"exp-s2-{label}"))
        checked = []
        for c in res.data["candidates"]:
            v = acc.check(c["cik"], c["tickers"], args.filters)
            checked.append({"rank": c["rank"], "name": c["name"], "tickers": c["tickers"],
                            "frame_value": c["values"]["fcf_margin"], "verdict": v.state})
        res_all[label] = {"members": len(members), "excluded_sectors": sorted(excl), "counts": res.data["counts"],
                          "rechecked": checked, "seconds_screen": round(ts, 1),
                          "accepted": sum(c["verdict"] == "pass" for c in checked),
                          "rejected": sum(c["verdict"] == "fail" for c in checked),
                          "unknown": sum(c["verdict"] == "unknown" for c in checked)}
        print(label, len(members), res.data["counts"], [(c["tickers"][0], c["frame_value"], c["verdict"]) for c in checked])
(OUT / "discover_s2_exfin.json").write_text(json.dumps(res_all, indent=2, default=str))
