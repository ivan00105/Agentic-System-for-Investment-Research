"""Second pass of the tool-oracle audit: gold items not in companyfacts concepts. Read the gold source filing
with read_filing_section (keyword query, as an agent would) and check whether the gold figure appears."""
import json, sys, glob, re
from datetime import datetime, time, timezone
from pathlib import Path
import yaml
from research_assistant.data.sec import SecClient
from research_assistant.tools.result import ToolContext
from research_assistant.tools import registry
REPO=Path(sys.argv[1]); rows=json.load(open(sys.argv[2])); sec=SecClient()
cases={yaml.safe_load(open(f))["id"]:yaml.safe_load(open(f)) for f in glob.glob(str(REPO/"eval/cases/*.yaml"))}
def forms(v):
    out={f"{v:,}", f"{v:,.1f}", f"{v:,.2f}", str(v)}
    if float(v).is_integer(): out.add(f"{int(v):,}")
    k=round(v*1000)
    out.add(f"{k:,}")
    return out
for row in rows:
    case=cases[row["id"]]; g_by={g["name"]:g for g in case.get("gold") or []}
    ctx=ToolContext(cutoff=datetime.combine(case["cutoff"],time.max,timezone.utc),sec=sec,historical=True)
    for it in row["items"]:
        if it["status"] not in ("text_or_calc","text_not_found"): continue
        g=g_by[it["name"]]; src=g.get("source") or {}
        comp=next((c for c in case["companies"] if c["ticker"]==(g.get("ticker") or case["companies"][0]["ticker"])),case["companies"][0])
        words=" ".join(w for w in it["name"].split("_") if not re.match(r"^(fy)?\d{4}$",w))
        words={"sbc":"stock-based compensation"}.get(words.split()[0],words) if words else words
        words=words.replace("sbc adjustment","stock-based compensation").replace("cash requirements next 12 months","material cash requirements next 12 months").replace("depreciation amortization","depreciation amortization content assets property")
        hit=None
        for item in ["8","7","1","5","2"]:
            args={"cik":str(comp["cik"]),"item":item,"query":words}
            if src.get("accession"): args["accession"]=src["accession"]
            r=registry.call("read_filing_section",args,ctx)
            if r.status!="ok": continue
            text=json.dumps(r.data,default=str)
            if any(f in text for f in forms(g["value"])): hit=item; break
        it["status"]="text_found" if hit else "text_not_found"; it["text_item"]=hit
        print(row["id"],it["name"],g["value"],it["status"],hit,flush=True)
json.dump(rows,open(sys.argv[2],"w"),indent=1,default=str)
