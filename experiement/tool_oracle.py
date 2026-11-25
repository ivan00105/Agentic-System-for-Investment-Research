"""Tool-oracle audit: for every eval case, call the agents' own deterministic tools (no LLM) at the case
cutoff and check whether the gold value is reachable. Also a second-source check of the labels against
SEC XBRL companyfacts. Nothing here is an agent score."""
import glob, json, sys, math
from datetime import datetime, time, timezone
from pathlib import Path
import yaml
from research_assistant.data.sec import SecClient
from research_assistant.data import sec_facts
from research_assistant.tools.result import ToolContext
from research_assistant.tools import registry

REPO = Path(sys.argv[1]); OUT = Path(sys.argv[2])
sec = SecClient()
rows = []
for f in sorted(glob.glob(str(REPO / "eval/cases/*.yaml"))):
    case = yaml.safe_load(open(f))
    cutoff = datetime.combine(case["cutoff"], time.max, timezone.utc)
    ctx = ToolContext(cutoff=cutoff, sec=sec, historical=True)
    ticker = (case.get("companies") or [{}])
    fc_query = case.get("ticker") or (ticker[0].get("ticker") if isinstance(ticker[0], dict) else None)
    row = {"id": case["id"], "type": case["case_type"], "behaviour": case["expected"]["behaviour"],
           "split": case.get("split"), "items": []}
    # resolve companies
    tickers = []
    for c in case.get("companies") or []:
        tickers.append(c.get("ticker") if isinstance(c, dict) else c)
    if not tickers and case.get("ticker"): tickers = [case["ticker"]]
    row["tickers"] = tickers
    ciks = {}
    for t in tickers:
        r = registry.call("find_company", {"query": t}, ctx)
        row.setdefault("find_company", {})[t] = r.status
    for c in case.get("companies") or []:
        if isinstance(c, dict) and c.get("cik"): ciks[c["ticker"]] = str(c["cik"])
    facts = {}
    for t, cik in ciks.items():
        if not cik: continue
        r = registry.call("get_financials", {"cik": cik, "years": 12}, ctx)
        recs = [ctx.records[i] for i in r.ids if i in ctx.records]
        facts[t] = (r.status, recs)
    found = {}
    for g in case.get("gold") or []:
        item = {"name": g["name"], "metric": g["metric"], "gold": g["value"], "derived": bool(g.get("derived")),
                "period_end": str(g.get("period_end")), "company": g.get("company") or g.get("ticker")}
        comp = item["company"] or (tickers[0] if tickers else None)
        if g.get("derived"):
            ins = g["derived"].get("inputs", [])
            if all(found.get(i, {}).get("status") == "match" for i in ins):
                env = {i: found[i]["gold"] for i in ins}
                try:
                    v = eval(g["derived"]["formula"], {"__builtins__": {}}, env)
                    unit = g.get("unit") or ""
                    v = v * 100 if unit == "percent" else v * 1e4 if unit == "basis points" else v * 100 if unit == "percentage points" else v
                    item["computed"] = v
                    item["status"] = "derived_ok" if abs(v - g["value"]) <= max(0.06, abs(g["value"]) * 0.01) else "derived_mismatch"
                except Exception as e:
                    item["status"] = "derived_err:" + str(e)[:40]
            else:
                item["status"] = "derived_inputs_missing"
        elif g["metric"] not in sec_facts.CONCEPTS:
            item["status"] = "text_or_calc"   # needs read_filing_section or calculate
        else:
            st, recs = facts.get(comp, ("none", []))
            scale = 1e6 if "millions" in (g.get("unit") or "") else 1
            hit = [x for x in recs if x["metric"] == g["metric"] and x["end"] == str(g.get("period_end"))]
            vals = sorted({float(x["value"]) / scale for x in hit})
            item["tool_values"] = vals
            tol = max(0.5, abs(g["value"]) * 0.001)
            if any(abs(v - g["value"]) <= tol for v in vals): item["status"] = "match"
            elif vals: item["status"] = "differs"
            else: item["status"] = "absent"
        found[g["name"]] = item
        row["items"].append(item)
    rows.append(row)
    print(row["id"], row.get("find_company"), [(i["name"], i["status"], i.get("tool_values")) for i in row["items"]], flush=True)
OUT.write_text(json.dumps(rows, indent=1, default=str))
