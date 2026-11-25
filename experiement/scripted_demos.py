"""Run selected scripted-model tests (tests/fake_llm.py) and summarise the trace each produces.
The model is scripted, so these show the host's agentic control flow, not model quality."""
import json, sys, collections, tempfile, importlib, inspect
from pathlib import Path
sys.path.insert(0, "tests")
import pytest
OUT = {}
def summarise(name, events):
    kinds = collections.Counter(e["kind"] for e in events)
    end = events[-1]
    tool_calls = sum(1 for e in events if e["kind"] in ("tool_call", "tool"))
    OUT[name] = {"events": len(events), "kinds": dict(kinds),
                 "status": end.get("status"), "by_agent": end.get("by_agent"),
                 "objections": [{k: o.get(k) for k in ("issue", "owner", "outcome", "version", "new_version", "closed_in")} for o in end.get("objections") or []],
                 "claim_versions": {k: len(v) for k, v in (end.get("claims") or {}).items()} if isinstance(end.get("claims"), dict) else None}
TESTS = [("test_agent_critic", "test_a_wrong_period_is_caught_routed_to_its_analyst_and_corrected_as_a_new_version", "run_d"),
         ("test_agent_critic", "test_outcomes_follow_the_ledger_and_what_is_open_at_the_guard_is_unresolved", "run_d"),
         ("test_agent_critic", "test_a_missing_risk_is_corrected_by_adding_a_claim", "run_d"),
         ("test_agent_team", "test_the_coordinator_asks_analysts_and_merges_their_findings", "run"),
         ("test_agent_team", "test_a_failed_analyst_is_reported_and_a_follow_up_continues_its_conversation", "run")]
for modname, test, runner in TESTS:
    mod = importlib.import_module(modname)
    orig = getattr(mod, runner)
    def wrapped(*a, _o=orig, _t=test, **k):
        res = _o(*a, **k); summarise(_t, res[2]); return res
    setattr(mod, runner, wrapped)
    with tempfile.TemporaryDirectory() as d:
        fn = getattr(mod, test)
        try:
            fn(Path(d)); OUT[test]["test_passed"] = True
        except Exception as e:
            OUT.setdefault(test, {})["error"] = repr(e)[:300]
    setattr(mod, runner, orig)
json.dump(OUT, open(sys.argv[1], "w"), indent=1, default=str)
for k, v in OUT.items(): print(k, json.dumps(v, default=str)[:900], "\n")
