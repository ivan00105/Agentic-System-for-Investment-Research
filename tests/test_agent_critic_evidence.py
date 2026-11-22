"""Condition D: only tool records close an objection, never a claim, the objected one included (Codex review)."""
import json
import re

import pytest
from fake_llm import resubmit
from test_agent_critic import CLEAN, COMPANY, PLAN, calls, claim_in, objection, run_d
from research_assistant.agents.checker import CheckedClaim, CheckedReport
from research_assistant.agents.critic import base_rate_misleading_certainty

SUMMARY = [{"text": "Apple Inc. files annual reports with the SEC.", "citations": [COMPANY]},
           {"text": "Apple Inc. is listed in the United States.", "citations": [COMPANY]}]
RISK = {"text": "Apple depends on a few suppliers.", "citations": [COMPANY]}


def answered(tmp_path, issue, answer):
    """One objection on summary[0]; `answer(draft)` may change the draft and returns the outcome and its citations."""
    def critic_round_1(messages):
        return calls(("submit_objections", {"objections": [
            objection(*claim_in(messages[1]["content"], "summary[0]"), issue)]}))

    def revise(messages):
        request = messages[-1]["content"]
        draft = json.loads(request[request.index("{"):])
        outcome, citations = answer(draft)
        return calls(("submit_revision", {**draft, "outcomes": [{
            "objection": re.search(r"- (objection-\w+) on", request)[1], "outcome": outcome,
            "explanation": "See the citations.", "citations": citations}]}))

    _, _, events = run_d(tmp_path, PLAN, calls(("find_company", {"query": "AAPL"})),
                         calls(("submit_report", {"summary": SUMMARY})), resubmit, critic_round_1, revise, CLEAN,
                         critic_rounds=2)
    [o] = events[-1]["objections"]
    return o


def reworded(draft):
    draft["summary"][0]["text"] = "Apple Inc. files 10-K reports with the SEC."
    return "corrected", [draft["summary"][0]["id"]]


@pytest.mark.parametrize("answer", [
    lambda draft: ("defended", [draft["summary"][0]["id"]]),  # the objected claim itself
    lambda draft: ("defended", [draft["summary"][1]["id"]]),  # another report claim
    reworded,  # a new version that cites only itself
])
def test_a_claim_cited_as_evidence_does_not_close_an_objection(tmp_path, answer):
    o = answered(tmp_path, "unsupported_inference", answer)
    assert (o["outcome"], o["new_version"]) == ("unresolved", None)
    assert any(note.startswith("Round 1: citing claims (claim-") for note in o["notes"])


def test_a_tool_record_cited_as_evidence_still_closes_an_objection(tmp_path):
    o = answered(tmp_path, "unsupported_inference", lambda draft: ("defended", [COMPANY]))
    assert (o["outcome"], o["citations"]) == ("defended", [COMPANY])


def in_summary(draft):
    draft["summary"].append(RISK)
    return "corrected", [COMPANY]


def outcome_cites_a_claim(draft):
    draft["risks"] = [RISK]
    return "corrected", [draft["summary"][0]["id"]]


@pytest.mark.parametrize("answer", [in_summary, outcome_cites_a_claim])
def test_a_missing_risk_needs_a_new_risks_claim_and_a_tool_record(tmp_path, answer):
    o = answered(tmp_path, "missing_material_risk", answer)
    assert (o["outcome"], o["new_claims"]) == ("unresolved", [])
    assert ("Round 1: a claim was added, but it stays open: that needs a new Risks claim and an outcome that each "
            "cite a tool record.") in o["notes"]


@pytest.mark.parametrize(("text", "metric"), [
    ("Revenue growth will reach 30% every year.", "revenue growth"),
    ("The bull case expects revenue growth of 25%.", "revenue growth"),
    ("Operating margin will expand by 15 percentage points.", "operating-margin change"),
])
def test_host_critic_flags_overoptimistic_base_rate_claims(text, metric):
    record = {
        "id": "base-rates-test",
        "kind": "calc",
        "formula": "base_rates",
        "data": {
            "growth": {"p10": "0.00", "p50": "0.10", "p90": "0.20"},
            "margin_change": {"p10": "-0.02", "p50": "0.01", "p90": "0.05"},
        },
    }
    claim = CheckedClaim(text=text, kind="interpretation", citations=[record["id"]],
                         materiality="central", id="claim-bull", version=1)
    report = CheckedReport(sections={"bull_case": [claim]}, limitations=[], flags=[], sources=[record["id"]])
    objections = base_rate_misleading_certainty(report, {record["id"]: record})
    assert len(objections) == 1
    assert objections[0].issue == "misleading_certainty"
    assert metric in objections[0].problem
    assert record["id"] in objections[0].evidence
