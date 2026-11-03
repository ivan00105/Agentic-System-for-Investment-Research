"""Pure calculations: no I/O, no network, no LLM. Every function says why when it can't give a value."""
from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class Outcome:
    value: Decimal | float | None
    reason: str | None = None  # why there is no value
    note: str | None = None  # a caveat that travels with the value
