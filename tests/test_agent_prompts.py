from research_assistant.agents import prompts
from research_assistant.agents.draft import Draft
from research_assistant.agents.objections import Objection, issue_list

ROLES = ("single_agent", "coordinator", "fundamentals", "filings", "market", "critic")
CUTOFF = "2026-11-03T23:59:59+00:00"


def test_every_role_gets_the_evidence_rules_and_the_plain_writing_rules():
    for name in ROLES:
        text = prompts.role(name, cutoff=CUTOFF)
        assert "Never type a figure" in text and "$rules" not in text and CUTOFF in text, name
        assert "One idea per claim" in text and "No tool or ID talk" in text, name
        assert "Caveats about method go in `limitations`" in text, name
        assert "What you remember is not evidence" in text, name


def test_the_critic_and_the_self_review_look_for_look_ahead():
    assert "`look_ahead`" in issue_list()
    text = prompts.role("critic", cutoff=CUTOFF, issues=issue_list())
    assert "- `look_ahead`: the statement uses something from after the research cutoff" in text
    assert "is `look_ahead`, even if it is true" in text
    found = Objection(claim="claim-a", version=1, issue="look_ahead", material=True, evidence=["filing-a"],
                      problem="It names a stock split announced after the cutoff.", requested_check="Withdraw it.")
    assert found.issue == "look_ahead"


def test_report_writers_put_the_answer_first_and_one_figure_per_key_number():
    for name in ("single_agent", "coordinator"):
        text = prompts.role(name, cutoff=CUTOFF)
        assert "Its first statement answers the question in one or two short sentences" in text, name
        assert "one figure per statement" in text, name
    schema = Draft.model_json_schema()["properties"]
    assert schema["summary"]["description"].startswith("The answer first")
    assert "caveats about how figures were found" in schema["limitations"]["description"]
