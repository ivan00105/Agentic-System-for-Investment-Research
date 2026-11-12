"""What the critic hands in and what the coordinator answers (REFERENCE §3), plus the view of a report both the
critic (condition D) and the self-review pass (conditions B and C) read, so they look for the same issue types with
the same evidence in front of them (REFERENCE §7)."""
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .checker import CheckedReport
from .draft import NUMBERS, SECTIONS, Draft, _citations_required
from .report import describe

# REFERENCE §3's issue types; "wrong period/unit/entity" is split in three so the evaluation can score each.
ISSUES = {
    "unsupported_inference": "the cited evidence doesn't support the statement, or the statement goes beyond it",
    "contradictory_evidence": "another record, cited or from a tool, says otherwise",
    "wrong_period": "a figure's fiscal period or date differs from the one the statement names, or compared "
                    "periods don't match",
    "wrong_unit": "a figure is in a different unit or scale than stated (%, percentage points, millions or "
                  "billions, per share)",
    "wrong_entity": "a figure belongs to a different company, segment or share class than the statement says",
    "arithmetic_error": "a calculation uses the wrong inputs or formula for what the statement calls it",
    "stale_source": "a newer filing or figure was available at the cutoff, or an old figure is presented as current",
    "misleading_certainty": "the statement is surer than its evidence: a management claim or a forecast stated as "
                            "fact, or a needed caveat left out",
    "missing_material_risk": "a material risk in the evidence (e.g. the 10-K's Item 1A) is missing from the report",
    # The model was trained after most eval cutoffs, so it may remember what came next.
    "look_ahead": "the statement uses something from after the research cutoff that no cited record shows, such as "
                  "a later event, result, price or filing the writer may remember",
}
Issue = Literal[tuple(ISSUES)]  # type: ignore[valid-type]
OUTCOMES = ("defended", "corrected", "withdrawn", "unresolved")


def issue_list() -> str:
    return "\n".join(f"- `{name}`: {text}." for name, text in ISSUES.items())


class Objection(BaseModel):
    # Listed as required for the model; a missing one still validates (and is noted), never rejected.
    model_config = ConfigDict(json_schema_extra=lambda schema: schema["required"].extend(["version", "evidence"]))

    claim: str = Field(description="The claim ID (claim-...) the objection is about. For a missing material risk, "
                                   "the claim it would qualify, usually a summary claim.")
    version: int | None = Field(None, description="The version of the claim you reviewed.")
    issue: Issue = Field(description="The kind of problem.")  # type: ignore[valid-type]
    material: bool = Field(description=(
        "true when the problem changes a figure, its period, unit or company, or the answer; false otherwise."))
    problem: str = Field(min_length=1, description="What is wrong and what shows it, in a sentence or two. " + NUMBERS)
    evidence: list[str] = Field(default_factory=list, description="IDs of the records that show the problem.")
    requested_check: str = Field(min_length=1, description=(
        "One check that would settle it, which the team can run with its tools, e.g. which figure to fetch, "
        "verify or recompute, or which filing section to read."))

    @field_validator("version", mode="before")
    @classmethod
    def _plain_number(cls, value):
        return value.strip().lstrip("vV") if isinstance(value, str) else value  # "v2" as models write it


class Objections(BaseModel):
    objections: list[Objection] = Field(default_factory=list, description=(
        "Zero or more, the most material first. A report the evidence supports gets none."))


class Outcome(BaseModel):
    model_config = ConfigDict(json_schema_extra=_citations_required)

    objection: str = Field(description="The objection ID (objection-...).")
    outcome: Literal[OUTCOMES] = Field(description=(  # type: ignore[valid-type]
        "defended: the evidence answers it; corrected: the claim is revised (same claim ID in `id`); withdrawn: "
        "the claim is removed; unresolved: no tool can settle it."))
    explanation: str = Field(description="What the check found, in a sentence or two. " + NUMBERS)
    citations: list[str] = Field(default_factory=list, description="IDs of the records that settle it.")


class Revision(Draft):
    outcomes: list[Outcome] = Field(default_factory=list, description="One outcome per objection.")


def claims_view(report: CheckedReport) -> str:
    """Every report claim with its ID, version and where it sits, as it reads with the numbers filled in."""
    lines = []
    for key, _ in SECTIONS:
        for i, c in enumerate(report.sections[key]):
            line = (f"- {c.id} v{c.version} [{key}[{i}], {c.kind}, {c.materiality}]: {c.text} "
                    f"(cites {', '.join(c.citations) or 'nothing'})")
            lines.append(line + "".join(f"\n  Flag: {flag.problem}" for flag in c.flags))
    return "\n".join(lines) or "(The report has no claims.)"


def evidence_view(ids: list[str], records: dict[str, dict]) -> str:
    """One line per record the claims cite, with the facts behind each calculation and each paragraph's text,
    so a statement's period, unit and company can be checked against its evidence."""
    queue, seen, lines = list(ids), set(), []
    while queue:
        record = records.get(rid := queue.pop(0))
        if record is None or rid in seen:
            continue
        seen.add(rid)
        lines.append(f"- {describe(record).rstrip()}" + (f"\n  Text: {record['text']}" if record.get("kind") == "chunk"
                                                          else ""))
        if record.get("kind") == "calc":
            queue += [i for i in (record.get("inputs") or {}).values() if isinstance(i, str)]
    return "\n".join(lines) or "(No evidence is cited.)"


def draft_with_ids(draft: Draft, report: CheckedReport) -> dict:
    """The draft as JSON with every claim's ID in `id`, so a revision can keep each claim's lineage."""
    data = draft.model_dump(mode="json", include={key for key, _ in SECTIONS} | {"limitations"})
    for key, _ in SECTIONS:
        for claim, checked in zip(data[key], report.sections[key], strict=True):
            claim["id"] = checked.id
    return data
