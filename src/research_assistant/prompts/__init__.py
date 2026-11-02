"""Packaged model instructions; schemas and execution policy stay in Python."""

from importlib.resources import files


def _read(name: str) -> str:
    return files(__package__).joinpath(name).read_text(encoding="utf-8").rstrip("\r\n")


_COMMON = _read("common.txt")
# Stable action labels; model instructions live in the packaged text files.
INTERPRETATION_ROLE = "Filings interpretation"
CRITIC_ROLE = "Critic: identify specific objections; request operating_margin or source_support checks"
_ROLE_INSTRUCTIONS = {
    INTERPRETATION_ROLE: _read("interpretation.txt"),
    CRITIC_ROLE: _read("critic.txt"),
}


def system_prompt(role: str) -> str:
    return f"{_COMMON} {_ROLE_INSTRUCTIONS[role]}"
