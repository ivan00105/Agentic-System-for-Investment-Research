import json
import re
from pathlib import Path

import pytest
from fake_llm import FakeClient, reply, resubmit, tool_results
from sec_files import make_context

from research_assistant import cli
from research_assistant.agents import critic, single_agent
from research_assistant.agents.checker import CheckedClaim, CheckedReport
from research_assistant.agents.claims import ClaimLedger
from research_assistant.agents.draft import Draft
from research_assistant.agents.evidence import inject_wrong_period
from research_assistant.agents.roles import CRITIC
from research_assistant.model_access import ModelSettings

SETTINGS = ModelSettings("openrouter", "OpenRouter", "fake-model", "key", "https://openrouter.ai/api/v1")
QUESTION = "How much revenue did Apple make?"
PLAN = reply("1. ask_fundamentals for revenue")
TASK = "Apple (AAPL, CIK 0000320193): revenue for the latest two fiscal years."
COMPANY = "company-0000320193"
CLEAN = reply(tool_calls=[("submit_objections", {"objections": []})])


def calls(*pairs):
    return reply(tool_calls=list(pairs))


def by_source(messages):
    return {result["source"]: result for result in tool_results(messages)}


def revenue(messages, n):
    return by_source(messages)["SEC companyfacts"]["data"]["metrics"]["revenue"]["values"][n]["id"]


def claim_in(brief, where):
    claim, version = re.search(rf"- (claim-\w+) v(\d+) \[{re.escape(where)},", brief).groups()
    return claim, int(version)


def objection(claim, version, issue, problem="It is wrong.", material=True, evidence=(COMPANY,)):
    return {"claim": claim, "version": version, "issue": issue, "material": material, "problem": problem,
            "evidence": list(evidence), "requested_check": "Check it with the tools."}


def events_at(path):
    return [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines()]


def printed_trace(out):
    return events_at(re.search(r"^Trace saved to (.+)$", out, re.MULTILINE)[1])


def configure(monkeypatch, tmp_path, client):
    for name, value in (("RESEARCH_MODEL_PROVIDER", "openrouter"), ("RESEARCH_MODEL", "fake-model"),
                        ("OPENROUTER_API_KEY", "test-key"), ("RESEARCH_DATA_DIR", str(tmp_path))):
        monkeypatch.setenv(name, value)
    monkeypatch.setattr(cli, "sec_client", lambda: make_context(tmp_path).sec)
    monkeypatch.setattr(cli, "model_client", lambda settings: client)


def run_d(tmp_path, *script, **options):
    client = FakeClient(*script)
    result = critic.run(QUESTION, client, SETTINGS, make_context(tmp_path), trace_dir=tmp_path / "traces", **options)
    return result, client, events_at(result.trace_path)


# The fundamentals analyst labels the prior year's revenue as the latest year's: a wrong-period error.
def financials(messages):
    return calls(("get_financials", {"cik": "0000320193", "metrics": ["revenue"], "years": 2}))


def wrong_finding(messages):
    return calls(("submit_findings", {"findings": [{
        "text": "Revenue was {fact:%s} in the fiscal year ended 2025-09-27." % revenue(messages, 1),
        "kind": "fact", "materiality": "central"}]}))


def report(messages):
    [finding] = by_source(messages)["fundamentals analyst"]["data"]["findings"]
    return calls(("submit_report", {"key_numbers": [{"text": finding["text"], "kind": "fact", "materiality": "central",
                                                     "id": finding["claim"]}]}))


def critic_objects(messages):
    brief = messages[1]["content"]
    assert "Review 1 of at most 3" in brief and "None: this is the first review." in brief
    claim, version = claim_in(brief, "key_numbers[0]")
    older = re.search(r"`(fact-\w+)` revenue = \$391\.0 billion, 2023-10-01 to 2024-09-28", brief)[1]
    return calls(("submit_objections", {"objections": [objection(
        claim, version, "wrong_period", "{fact:%s} is for the fiscal year ended 2024-09-28, not 2025-09-27." % older,
        evidence=[older])]}))


def route(messages):
    request = messages[-1]["content"]
    assert "(key_numbers[0]; owner: ask_fundamentals): wrong_period, material." in request
    assert '"id": "claim-' in request  # the current report, with claim IDs to keep
    found = re.search(r"- (objection-\w+) on (claim-\w+) v1", request)
    return calls(("ask_fundamentals", {"task": f"{found[1]} on {found[2]}: use the fiscal year ended 2025-09-27."}))


def corrected_finding(messages):
    follow_up = messages[-1]["content"]
    assert follow_up.startswith("Follow-up from the coordinator:\nobjection-")
    claim = re.search(r"- (claim-\w+) v1: Revenue was \{fact:", follow_up)[1]
    return calls(("submit_findings", {"findings": [{
        "text": "Revenue was {fact:%s} in the fiscal year ended 2025-09-27." % revenue(messages, 0),
        "kind": "fact", "materiality": "central", "id": claim}]}))


def revise(messages):
    request = next(m["content"] for m in reversed(messages) if "raised these objections" in str(m.get("content")))
    found = re.search(r"- (objection-\w+) on", request)[1]
    [finding] = by_source(messages)["fundamentals analyst"]["data"]["findings"]
    return calls(("submit_revision", {
        "key_numbers": [{"text": finding["text"], "kind": "fact", "materiality": "central", "id": finding["claim"]}],
        "outcomes": [{"objection": found, "outcome": "corrected", "citations": finding["citations"],
                      "explanation": "The figure is now the fiscal year ended 2025-09-27: {fact:%s}."
                                     % finding["citations"][0]}]}))


def critic_clean_after_the_fix(messages):
    brief = messages[1]["content"]
    assert "Review 2 of at most 3" in brief and "Outcome: corrected (now v2)" in brief
    assert "Revenue was $416.2 billion in the fiscal year ended 2025-09-27." in brief
    return CLEAN


def test_a_wrong_period_is_caught_routed_to_its_analyst_and_corrected_as_a_new_version(tmp_path):
    result, client, events = run_d(tmp_path, PLAN, calls(("ask_fundamentals", {"task": TASK})), financials,
                                   wrong_finding, report, resubmit, critic_objects, route, corrected_finding, revise,
                                   critic_clean_after_the_fix)
    assert result.status == "finished" and not result.report.flags
    # The critic runs its own loop with read-only tools plus verify_against_filing.
    assert {t["function"]["name"] for t in client.requests[6]["tools"]} == {*CRITIC.tools, "submit_objections"}
    assert "verify_against_filing" in CRITIC.tools and "screen" not in CRITIC.tools
    # The follow-up continues the analyst's conversation.
    assert client.requests[8]["messages"][1]["content"].endswith(f"Your task from the coordinator:\n{TASK}")

    [o] = events[-1]["objections"]
    claim = result.report.sections["key_numbers"][0]
    assert (o["claim"], o["version"], o["issue"], o["owner"]) == (claim.id, 1, "wrong_period", "fundamentals")
    assert (o["outcome"], o["closed_in"], o["new_version"], o["notes"]) == ("corrected", 1, 2, [])
    assert o["citations"] == claim.citations and o["evidence"] != claim.citations
    assert claim.version == 2 and claim.text == "Revenue was $416.2 billion in the fiscal year ended 2025-09-27."
    assert [v["author"] for v in events[-1]["claims"][claim.id]] == ["fundamentals", "fundamentals"]
    kinds = [e["kind"] for e in events]
    assert kinds.count("critic_start") == 2 and kinds.count("revision_start") == kinds.count("outcomes") == 1
    assert events[-1]["by_agent"]["critic"]["model_calls"] == 2 and events[-1]["withdrawn"] == {}

    assert "- Condition: D (analyst team + critic)" in result.markdown and "## Review" in result.markdown
    assert (f"- `{o['id']}` on `{claim.id}` v1 (wrong period, material, round 1, owner: fundamentals analyst): "
            "$391.0 billion is for the fiscal year ended 2024-09-28, not 2025-09-27. [2]") in result.markdown
    assert ("  - Outcome: corrected as v2 in round 1: The figure is now the fiscal year ended 2025-09-27: "
            "$416.2 billion. [1]") in result.markdown


def test_a_clean_report_gets_no_objections_and_stays_unchanged(tmp_path, monkeypatch, capsys):
    configure(monkeypatch, tmp_path, FakeClient(PLAN, calls(("find_company", {"query": "AAPL"})), calls((
        "submit_report", {"summary": [{"text": "Apple Inc. files annual reports with the SEC.",
                                       "citations": [COMPANY]}]})), resubmit, CLEAN))
    assert cli.main([QUESTION, "--condition", "D"]) == 0
    out, err = capsys.readouterr()
    assert "- Condition: D (analyst team + critic)" in out and "## Review" not in out
    assert "[critic] review round 1" in err and "[critic] round 1: 0 objections (0 material), 0 repeats" in err
    events = printed_trace(out)
    assert [e["kind"] for e in events].count("critic_start") == 1 and "revision_start" not in [e["kind"] for e in events]
    assert events[-1]["objections"] == [] and all(len(v) == 1 for v in events[-1]["claims"].values())


def test_outcomes_follow_the_ledger_and_what_is_open_at_the_guard_is_unresolved(tmp_path):
    def critic_round_1(messages):
        brief = messages[1]["content"]
        summary, bull = claim_in(brief, "summary[0]"), claim_in(brief, "bull_case[0]")
        return calls(("submit_objections", {"objections": [
            objection(*bull, "misleading_certainty"), objection(*summary, "unsupported_inference"),
            objection("claim-nope", 1, "wrong_entity", evidence=["fact-made-up"])]}))

    def withdraw_and_defend(messages):
        request = messages[-1]["content"]
        assert "owner: you (no analyst finding behind it)" in request
        ids = re.findall(r"- (objection-\w+) on", request)
        summary = json.loads(request[request.index("{"):])["summary"]
        return calls(("submit_revision", {"summary": summary, "outcomes": [
            {"objection": ids[0], "outcome": "withdrawn", "explanation": "It was an opinion.", "citations": [COMPANY]},
            {"objection": ids[1], "outcome": "defended", "explanation": "It is fine.", "citations": []},
            {"objection": "objection-unknown", "outcome": "defended", "explanation": "?", "citations": [COMPANY]}]}))

    def critic_round_2(messages):
        brief = messages[1]["content"]
        assert "Note: Round 1: defended without citing evidence, so it stays open." in brief
        summary = claim_in(brief, "summary[0]")
        return calls(("submit_objections", {"objections": [
            objection(*summary, "unsupported_inference", "Still unsupported."),
            objection(*summary, "wrong_entity", "Named 3 times.", material=False, evidence=[summary[0]])]}))

    result, client, events = run_d(
        tmp_path, PLAN, calls(("find_company", {"query": "AAPL"})), calls(("submit_report", {
            "summary": [{"text": "Apple Inc. files annual reports with the SEC.", "citations": [COMPANY]}],
            "bull_case": [{"text": "Apple is the strongest company in its sector.", "citations": [COMPANY]}]})),
        resubmit, critic_round_1, withdraw_and_defend, critic_round_2, critic_rounds=2)
    assert result.status == "finished" and len(client.requests) == 7
    withdrawn, defended, unknown, minor = events[-1]["objections"]
    summary = result.report.sections["summary"][0]
    assert withdrawn["outcome"] == "withdrawn" and withdrawn["closed_in"] == 1
    assert events[-1]["withdrawn"] == {withdrawn["claim"]: {"version": 1, "objection": withdrawn["id"]}}
    assert defended["outcome"] == "unresolved" and defended["notes"] == [
        "Round 1: defended without citing evidence, so it stays open.",
        "Still open after the last review allowed (AGENT_CRITIC_ROUNDS = 2), so it was not routed to the team."]
    assert unknown["outcome"] == "unresolved" and unknown["closed_in"] == 1 and unknown["notes"] == [
        "Evidence 'fact-made-up' is not an ID any tool returned.", "It cites no evidence.",
        "Not routed: it names no claim in the current report."]
    assert (minor["outcome"], minor["material"], minor["round"]) == ("unresolved", False, 2)
    assert minor["notes"][0] == "The problem types '3' instead of placeholders, so no tool result backs it."
    assert minor["evidence"] == [summary.id]  # a report claim cited as evidence resolves, though it is no record
    rounds = [e for e in events if e["kind"] == "objections"]
    assert rounds[1]["repeats"] == [{"claim": summary.id, "version": 1, "issue": "unsupported_inference",
                                     "repeat_of": defended["id"]}]
    assert next(e for e in events if e["kind"] == "outcomes")["unknown_objections"] == ["objection-unknown"]
    # The material objection left unresolved qualifies its claim; the minor one doesn't.
    assert [f.problem for f in summary.flags] == [
        f"Objection {defended['id']} (unsupported inference) is unresolved: It is wrong."]
    assert "## Summary (qualified)" in result.markdown and "## Bull case (abstained)" in result.markdown
    assert "  - Outcome: withdrawn in round 1: It was an opinion. [1]" in result.markdown


def test_a_missing_risk_is_corrected_by_adding_a_claim(tmp_path):
    def critic_round_1(messages):
        return calls(("submit_objections", {"objections": [
            objection(*claim_in(messages[1]["content"], "summary[0]"), "missing_material_risk")]}))

    def add_a_risk(messages):
        request = messages[-1]["content"]
        draft = json.loads(request[request.index("{"):])
        draft["risks"] = [{"text": "Apple depends on a few suppliers.", "citations": [COMPANY]}]
        return calls(("submit_revision", {**draft, "outcomes": [{
            "objection": re.search(r"- (objection-\w+) on", request)[1], "outcome": "corrected",
            "explanation": "Added the supplier risk.", "citations": [COMPANY]}]}))

    result, _, events = run_d(tmp_path, PLAN, calls(("find_company", {"query": "AAPL"})), calls((
        "submit_report", {"summary": [{"text": "Apple Inc. files annual reports with the SEC.",
                                       "citations": [COMPANY]}]})), resubmit, critic_round_1, add_a_risk, CLEAN)
    [o] = events[-1]["objections"]
    risk, summary = result.report.sections["risks"][0], result.report.sections["summary"][0]
    assert (o["outcome"], o["new_version"], o["new_claims"], summary.version) == ("corrected", None, [risk.id], 1)
    assert f"  - Outcome: corrected by adding `{risk.id}` in round 1: Added the supplier risk. [1]" in result.markdown


def saved_run(tmp_path, historical=False):
    """A condition B run whose key number is the latest fiscal year's revenue, with three years in the evidence."""
    def submit(messages):
        latest = revenue(messages, 0)
        return calls(("submit_report", {
            "summary": [{"text": "Apple's revenue grew.", "citations": [latest, revenue(messages, 1)]}],
            "key_numbers": [{"text": "Revenue was {fact:%s} in the fiscal year ended 2025-09-27." % latest,
                             "kind": "fact", "materiality": "central"}]}))

    client = FakeClient(reply("1. get_financials"), calls(("get_financials", {"cik": "0000320193", "metrics":
                                                                             ["revenue"], "years": 3})), submit,
                        resubmit)
    context = make_context(tmp_path)
    context.historical = historical
    return single_agent.run(QUESTION, client, SETTINGS, context, trace_dir=tmp_path / "traces")


def test_the_injected_period_moves_one_figure_to_the_latest_earlier_year_it_does_not_use():
    records = {r["id"]: r for r in (
        {"id": "fact-a", "kind": "fact", "cik": "1", "metric": "revenue", "unit": "USD", "start": "x", "end": "2025"},
        {"id": "fact-b", "kind": "fact", "cik": "1", "metric": "revenue", "unit": "USD", "start": "x", "end": "2024"},
        {"id": "fact-c", "kind": "fact", "cik": "1", "metric": "revenue", "unit": "USD", "start": "x", "end": "2023"},
        {"id": "fact-d", "kind": "fact", "cik": "2", "metric": "revenue", "unit": "USD", "start": "x", "end": "2022"})}
    draft = Draft(summary=["Revenue was {fact:fact-a}."],
                  key_numbers=[{"text": "Revenue {fact:fact-a}, up from {fact:fact-b}.", "id": "claim-x"}])
    changed, change = inject_wrong_period(draft, records)
    assert changed.key_numbers[0].text == "Revenue {fact:fact-c}, up from {fact:fact-b}." and changed.key_numbers[0].id
    assert changed.summary == draft.summary and draft.key_numbers[0].text.startswith("Revenue {fact:fact-a}")
    assert change == ("key_numbers[0]: fact-a (revenue, period ending 2025) was replaced by fact-c (period ending "
                      "2023); the words are unchanged.")
    assert inject_wrong_period(Draft(summary=["Revenue was {fact:fact-d}."]), records) is None


def test_the_cli_reviews_a_saved_draft_with_an_injected_wrong_period(tmp_path, monkeypatch, capsys):
    path = saved_run(tmp_path).trace_path

    def critic_catches_it(messages):
        brief = messages[1]["content"]
        assert "Revenue was $391.0 billion in the fiscal year ended 2025-09-27." in brief
        claim, version = claim_in(brief, "key_numbers[0]")
        return calls(("submit_objections", {"objections": [objection(claim, version, "wrong_period")]}))

    def fix(messages):
        request = messages[-1]["content"]
        draft = json.loads(request[request.index("{"):])
        latest = draft["summary"][0]["citations"][0]
        draft["key_numbers"][0]["text"] = "Revenue was {fact:%s} in the fiscal year ended 2025-09-27." % latest
        return calls(("submit_revision", {**draft, "outcomes": [{
            "objection": re.search(r"- (objection-\w+) on", request)[1], "outcome": "corrected",
            "explanation": "Put back the fiscal 2025 figure.", "citations": [latest]}]}))

    configure(monkeypatch, tmp_path, FakeClient(critic_catches_it, fix, CLEAN, CLEAN))
    assert cli.main(["--review", str(path), "--inject", "wrong_period"]) == 0
    out, err = capsys.readouterr()
    assert f"- Condition: D review of saved run {path.stem}, with an injected wrong_period defect" in out
    assert "- Test defect injected before the review (wrong_period): key_numbers[0]: fact-" in out
    assert "- Revenue was $416.2 billion in the fiscal year ended 2025-09-27. [" in out
    assert "  - Outcome: corrected as v3 in round 1: Put back the fiscal 2025 figure." in out
    assert "[coordinator] injected wrong_period: key_numbers[0]" in err
    events = printed_trace(out)
    claim = events[-1]["objections"][0]["claim"]
    assert [v["author"] for v in events[-1]["claims"][claim]] == ["single_agent", "injected", "coordinator"]

    # The same saved draft without a defect: the critic objects to nothing and every claim stays as it was.
    assert cli.main(["--review", str(path)]) == 0
    out, _ = capsys.readouterr()
    events = printed_trace(out)
    assert events[-1]["objections"] == [] and all(len(v) == 1 for v in events[-1]["claims"].values())
    assert "- Revenue was $416.2 billion in the fiscal year ended 2025-09-27. [" in out
    # No tool ran in that review, but its trace froze the evidence it started from, so it stands on its own.
    review = Path(re.search(r"^Trace saved to (.+)$", out, re.MULTILINE)[1])
    assert cli.main(["--recheck", str(review)]) == 0
    assert "Every number matches the saved run." in capsys.readouterr().out


def test_inject_needs_a_saved_run_to_review(capsys):
    with pytest.raises(SystemExit) as exc:
        cli.main(["--inject", "wrong_period"])
    assert exc.value.code == 2 and "--inject needs --review TRACE" in capsys.readouterr().err


def test_a_review_of_a_historical_run_stays_historical(tmp_path, monkeypatch, capsys):
    path = saved_run(tmp_path, historical=True).trace_path

    def critic_objects(messages):
        claim, version = claim_in(messages[1]["content"], "key_numbers[0]")
        return calls(("submit_objections", {"objections": [objection(claim, version, "wrong_period")]}))

    def leave_it(messages):
        request = next(m["content"] for m in reversed(messages) if "raised these objections" in str(m.get("content")))
        draft = json.loads(request[request.index("{"):])
        return calls(("submit_revision", {**draft, "outcomes": [{
            "objection": re.search(r"- (objection-\w+) on", request)[1], "outcome": "unresolved",
            "explanation": "No screen as of the cutoff.", "citations": [COMPANY]}]}))

    screen = calls(("screen", {"universe": ["AAPL"], "rank_by": "revenue", "year": 2024}))
    configure(monkeypatch, tmp_path, FakeClient(critic_objects, screen, leave_it, CLEAN))
    assert cli.main(["--review", str(path)]) == 0
    events = printed_trace(capsys.readouterr().out)
    assert events[0]["historical"] is True
    assert [e["result"]["status"] for e in events if e["kind"] == "tool_call"] == ["invalid"]


@pytest.mark.parametrize("outcomes,why", [
    ([], "no outcome was given"),
    ([{"outcome": "corrected", "citations": [], "explanation": "Fixed it."}], "corrected without a citation"),
])
def test_a_new_version_alone_does_not_close_an_objection_as_corrected(tmp_path, outcomes, why):
    # Codex review: any new claim version closed its objection as corrected, with no outcome or evidence.
    def revise_without_evidence(messages):
        request = next(m["content"] for m in reversed(messages) if "raised these objections" in str(m.get("content")))
        found = re.search(r"- (objection-\w+) on", request)[1]
        [finding] = by_source(messages)["fundamentals analyst"]["data"]["findings"]
        return calls(("submit_revision", {
            "key_numbers": [{"text": finding["text"], "kind": "fact", "materiality": "central", "id": finding["claim"]}],
            "outcomes": [{"objection": found, **outcome} for outcome in outcomes]}))

    def objects(messages):
        claim, version = claim_in(messages[1]["content"], "key_numbers[0]")
        return calls(("submit_objections", {"objections": [objection(claim, version, "wrong_period")]}))

    result, _, events = run_d(tmp_path, PLAN, calls(("ask_fundamentals", {"task": TASK})), financials, wrong_finding,
                              report, resubmit, objects, route, corrected_finding, revise_without_evidence, CLEAN,
                              critic_rounds=2)
    [o] = events[-1]["objections"]
    assert (o["outcome"], o["new_version"]) == ("unresolved", None)
    assert f"Round 1: the claim changed to v2, but no evidence it fixes the problem ({why}), so it stays open." \
        in o["notes"]


def test_a_claim_citing_one_with_an_unresolved_objection_is_flagged_one_level_only():
    def claim(claim_id, *cites):
        return CheckedClaim(f"Text of {claim_id}.", "interpretation", list(cites), [], "central", claim_id, 1)

    report = CheckedReport({"summary": [claim("claim-a"), claim("claim-b", "claim-a"), claim("claim-c", "claim-b")]},
                           [], [], [])
    review = critic.Critic(QUESTION, None, SETTINGS, None, None, ClaimLedger(), None, 1, 1)
    review.raised = [critic.Raised("objection-1", 1, "claim-a", 1, "summary[0]", "coordinator", "wrong_period", True,
                                   "Wrong year.", [], "Check it.", outcome="unresolved")]
    review._qualify(report)
    a, b, c = report.sections["summary"]
    assert [f.problem for f in a.flags] == ["Objection objection-1 (wrong period) is unresolved: Wrong year."]
    assert [f.problem for f in b.flags] == ["It cites claim-a, which has unresolved objection objection-1 (wrong "
                                            "period)."]
    assert c.flags == [] and len(report.flags) == 2
