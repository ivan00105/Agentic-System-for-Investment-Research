"""The report draft an agent hands in. Numbers are {fact:ID}/{calc:ID} placeholders that the host fills."""
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

NUMBERS = ("Write every number as a placeholder the host fills from tool results: {fact:ID} for a value from "
           "get_financials, {calc:ID} for a calculate result. Never type a figure yourself.")


def _citations_required(schema: dict) -> None:
    # Live check 3 Nov 2026: the coordinator left the optional `citations` key out of every interpretation, even
    # after the self-review asked for citations. The schema the model reads now lists it as required; a claim
    # without it still validates (as no citations) and is flagged by the checker, never rejected.
    schema["required"] = [*schema.get("required", []), "citations"]


class Claim(BaseModel):
    model_config = ConfigDict(json_schema_extra=_citations_required)

    text: str = Field(description="One statement. " + NUMBERS)
    citations: list[str] = Field(default_factory=list, description=(
        "IDs of the records the statement rests on (fact-, calc-, chunk-, filing-, company-, prices-, check-). "
        "IDs used in placeholders count automatically."))
    kind: Literal["fact", "calculation", "interpretation"] = Field("interpretation", description=(
        "fact: a reported value; calculation: a calculate result; interpretation: your reading of the evidence "
        "(cite the evidence it rests on)."))
    materiality: Literal["central", "supporting", "minor"] = Field("supporting", description=(
        "central: the answer depends on it; supporting: it backs a central claim; minor: context."))
    id: str | None = Field(None, description=(
        "Leave empty for a new statement. When you revise or repeat a statement that already has a claim ID "
        "(claim-...), put that ID here so the change is recorded as a new version of the same claim."))

    @model_validator(mode="before")
    @classmethod
    def _plain_text(cls, value):
        # A bare string is accepted as an uncited interpretation; the checker flags it instead of rejecting it.
        return {"text": value} if isinstance(value, str) else value


def _section(what: str):
    return Field(default_factory=list, description=what)


class Draft(BaseModel):
    summary: list[Claim] = _section("The answer first: one or two short sentences that answer the question, then "
                                    "the main takeaways, one idea each.")
    key_numbers: list[Claim] = _section("The figures the answer rests on, one per statement, each labelled with its "
                                        "metric and period.")
    bull_case: list[Claim] = _section("The strongest evidence-based case for the company.")
    bear_case: list[Claim] = _section("The strongest evidence-based case against it.")
    risks: list[Claim] = _section("Material risks, attributed to their source (e.g. the 10-K's Item 1A).")
    what_would_change_view: list[Claim] = _section("Observable developments that would change the conclusion.")
    limitations: list[str] = Field(default_factory=list, description=(
        "What could not be checked: missing or unsupported data, tools that failed, questions not answered, and "
        "caveats about how figures were found or calculated."))


class Findings(BaseModel):
    """What an analyst hands the coordinator (condition C); the coordinator merges findings into a Draft."""

    findings: list[Claim] = _section("What you found, one statement per claim, the most important first.")
    gaps: list[str] = Field(default_factory=list, description=(
        "What you could not find, check or calculate, and why."))


# Report order and headings (the coordinator's report uses the same shape as the single agent's).
SECTIONS = (("summary", "Summary"), ("key_numbers", "Key numbers"), ("bull_case", "Bull case"),
            ("bear_case", "Bear case"), ("risks", "Risks"), ("what_would_change_view", "What would change the view"))
