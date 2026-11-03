from research_assistant.agents.checker import check
from research_assistant.agents.claims import ClaimLedger, report_claims
from research_assistant.agents.draft import Draft

REVENUE = {"id": "fact-aaa111", "kind": "fact", "metric": "revenue", "unit": "USD", "value": "416161000000",
           "start": "2024-09-29", "end": "2025-09-27"}
MARGIN = {"id": "calc-bbb222", "kind": "calc", "formula": "ratio", "unit": "ratio", "value": "0.319708",
          "start": "2024-09-29", "end": "2025-09-27"}
RECORDS = {r["id"]: r for r in (REVENUE, MARGIN)}


def stamp(ledger, author="single_agent", **sections):
    draft = Draft(**sections)
    report = check(draft, RECORDS)
    return report, ledger.stamp(author, report_claims(draft, report))


def test_claims_keep_their_id_and_get_a_new_version_only_when_they_change():
    ledger = ClaimLedger()
    first, changes = stamp(ledger, summary=[{"text": "Revenue was {fact:fact-aaa111}.", "materiality": "central"}],
                           bull_case=[{"text": "Margins are high.", "citations": ["calc-bbb222"]}],
                           risks=[{"text": "Margins could fall.", "citations": ["calc-bbb222"]}])
    summary, bull, risk = (first.sections[key][0] for key in ("summary", "bull_case", "risks"))
    assert summary.id.startswith("claim-") and summary.version == 1 and summary.materiality == "central"
    assert len(changes["new"]) == 3 and not changes["revised"] and not changes["dropped"]

    # Revised with its ID kept, repeated unchanged without an ID, one dropped, one new.
    second, changes = stamp(ledger, summary=[{"text": "Revenue was {fact:fact-aaa111}.", "materiality": "central"}],
                            bull_case=[{"text": "The operating margin was {calc:calc-bbb222}.", "id": bull.id}],
                            bear_case=[{"text": "Revenue depends on one product.", "citations": ["fact-aaa111"]}])
    assert (second.sections["summary"][0].id, second.sections["summary"][0].version) == (summary.id, 1)
    assert (second.sections["bull_case"][0].id, second.sections["bull_case"][0].version) == (bull.id, 2)
    assert changes["unchanged"] == [summary.id] and changes["revised"] == [f"{bull.id} v2"]
    assert changes["dropped"] == [risk.id] and len(changes["new"]) == 1
    v1, v2 = ledger.versions[bull.id]
    assert v1["text"] == "Margins are high." and v2["reads"] == "The operating margin was 32.0%."
    assert v2["author"] == "single_agent" and v2["where"] == "bull_case[0]" and v2["status"] == "cited"


def test_ids_are_stable_and_unknown_or_duplicate_ids_are_noted_not_rejected():
    one, _ = stamp(ClaimLedger(), risks=["Competition is intense."])
    two, _ = stamp(ClaimLedger(), summary=["Competition is intense."])
    assert one.sections["risks"][0].id == two.sections["summary"][0].id  # same wording, same ID

    ledger = ClaimLedger()
    report, changes = stamp(ledger, risks=[{"text": "Supply risk.", "id": "claim-made-up"}, "Supply risk."])
    first, second = report.sections["risks"]
    assert first.id != second.id and first.version == second.version == 1
    assert "'claim-made-up' is not a claim ID from an earlier draft" in changes["notes"][0]
    # The ID is accepted in the forms models write it.
    again, changes = stamp(ledger, risks=[{"text": "Supply risk is high.", "id": first.id.replace("claim-", "claim:")}])
    assert again.sections["risks"][0].id == first.id and again.sections["risks"][0].version == 2


def test_roles_have_separate_drafts_but_a_copied_claim_keeps_its_lineage():
    ledger = ClaimLedger()
    finding, _ = stamp(ledger, "fundamentals", key_numbers=[{"text": "Revenue was {fact:fact-aaa111}.", "kind": "fact"}])
    report, changes = stamp(ledger, "coordinator", key_numbers=[{"text": "Revenue was {fact:fact-aaa111}.",
                                                                 "kind": "fact"}])
    assert report.sections["key_numbers"][0].id == finding.sections["key_numbers"][0].id
    assert changes["unchanged"] == [finding.sections["key_numbers"][0].id] and not changes["dropped"]
    assert ledger.latest == {"fundamentals": [finding.sections["key_numbers"][0].id],
                             "coordinator": [finding.sections["key_numbers"][0].id]}
