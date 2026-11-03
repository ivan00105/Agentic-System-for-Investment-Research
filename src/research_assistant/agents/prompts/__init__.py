"""Agent prompts, one .md file per role (PROJECT_GUIDE §8).

Values are filled with string.Template ($name), so literal braces such as {fact:ID} stay as written.
"""
from importlib.resources import files
from string import Template


def load(name: str, **values) -> str:
    text = files(__package__).joinpath(f"{name}.md").read_text(encoding="utf-8")
    return Template(text).safe_substitute(values)
