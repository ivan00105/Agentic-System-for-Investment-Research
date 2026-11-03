"""Claim IDs and versions (REFERENCE §3), so a revision shows exactly which claim changed.

A claim keeps its ID across drafts, and its version goes up only when its content changes: text, resolved
citations, kind or materiality. The model keeps an ID by repeating it in the claim's `id`. A claim without
one gets an ID from its wording, so a statement handed in again unchanged is still the same claim, and the
same statement copied by another role (an analyst's finding in the coordinator's report) keeps its lineage.
"""
from ..tools.result import make_id
from .checker import CheckedClaim, CheckedReport
from .draft import SECTIONS, Claim, Draft

CONTENT = ("text", "citations", "kind", "materiality")


def report_claims(draft: Draft, report: CheckedReport) -> list[tuple[str, Claim, CheckedClaim]]:
    """Each claim of a report draft with its checked form, labelled by where it sits (e.g. "risks[1]")."""
    return [(f"{key}[{i}]", claim, checked) for key, _ in SECTIONS
            for i, (claim, checked) in enumerate(zip(getattr(draft, key), report.sections[key], strict=True))]


class ClaimLedger:
    """Every version of every claim in one run, oldest first. It only records; it never rejects a claim."""

    def __init__(self):
        self.versions: dict[str, list[dict]] = {}  # claim ID -> its versions
        self.latest: dict[str, list[str]] = {}  # author -> claim IDs in that author's latest draft

    def stamp(self, author: str, claims: list[tuple[str, Claim, CheckedClaim]]) -> dict:
        """Give each (where, claim, checked) of one draft its ID and version, set on the CheckedClaim.
        Returns what changed since the author's previous draft, for the trace."""
        changes = {"new": [], "revised": [], "unchanged": [], "dropped": [], "notes": []}
        taken: list[str] = []
        for where, claim, checked in claims:
            claim_id = self._id(claim, where, taken, changes["notes"])
            taken.append(claim_id)
            content = {"text": claim.text, "citations": checked.citations, "kind": claim.kind,
                       "materiality": claim.materiality}
            history = self.versions.setdefault(claim_id, [])
            if history and all(history[-1][key] == content[key] for key in CONTENT):
                changes["unchanged"].append(claim_id)
            else:
                history.append({"id": claim_id, "version": len(history) + 1, "author": author, "where": where,
                                **content, "reads": checked.text, "status": checked.status})
                changes["revised" if len(history) > 1 else "new"].append(f"{claim_id} v{len(history)}")
            checked.id, checked.version = claim_id, history[-1]["version"]
        changes["dropped"] = [i for i in self.latest.get(author, []) if i not in taken]
        self.latest[author] = taken
        return changes

    def _id(self, claim: Claim, where: str, taken: list[str], notes: list[str]) -> str:
        if claim.id:
            raw = claim.id.strip().strip("{}").strip()
            known = next((i for i in (raw, "claim-" + raw.removeprefix("claim:").strip()) if i in self.versions), None)
            if known and known not in taken:
                return known
            notes.append(f"{where}: {claim.id!r} is not a claim ID from an earlier draft, or is used twice, "
                         "so the statement got its own ID.")
        n = 0
        while (claim_id := make_id("claim", claim.text, *([n] if n else []))) in taken:
            n += 1  # the same wording twice in one draft: two claims
        return claim_id
