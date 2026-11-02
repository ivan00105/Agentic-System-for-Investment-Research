"""The report draft an agent hands in. Numbers are {fact:ID}/{calc:ID} placeholders that the host fills."""
from typing import Literal

from pydantic import BaseModel, Field, model_validator

NUMBERS = ("Write every number as a placeholder the host fills from tool results: {fact:ID} for a value from "
           "get_financials, {calc:ID} for a calculate result. Never type a figure yourself.")


class Claim(BaseModel):
    text: str = Field(description="One statement. " + NUMBERS)
    citations: list[str] = Field(default_factory=list, description=(
        "IDs of the records the statement rests on (fact-, calc-, chunk-, filing-, company-, prices-, check-). "
        "IDs used in placeholders count automatically."))
    kind: Literal["fact", "calculation", "interpretation"] = Field("interpretation", description=(
        "fact: a reported value; calculation: a calculate result; interpretation: your reading of the evidence "
        "(cite the evidence it rests on)."))

    @model_validator(mode="before")
    @classmethod
    def _plain_text(cls, value):
        # A bare string is accepted as an uncited interpretation; the checker flags it instead of rejecting it.
        return {"text": value} if isinstance(value, str) else value


def _section(what: str):
    return Field(default_factory=list, description=what)


class Draft(BaseModel):
    summary: list[Claim] = _section("The direct answer to the question.")
    key_numbers: list[Claim] = _section("The figures the answer rests on, each labelled with its period.")
    bull_case: list[Claim] = _section("The strongest evidence-based case for the company.")
    bear_case: list[Claim] = _section("The strongest evidence-based case against it.")
    risks: list[Claim] = _section("Material risks, attributed to their source (e.g. the 10-K's Item 1A).")
    what_would_change_view: list[Claim] = _section("Observable developments that would change the conclusion.")
    limitations: list[str] = Field(default_factory=list, description=(
        "What could not be checked: missing or unsupported data, tools that failed, questions not answered."))


# Report order and headings (the coordinator's report in Phase 3 uses the same shape).
SECTIONS = (("summary", "Summary"), ("key_numbers", "Key numbers"), ("bull_case", "Bull case"),
            ("bear_case", "Bear case"), ("risks", "Risks"), ("what_would_change_view", "What would change the view"))
