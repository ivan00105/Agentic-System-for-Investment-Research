"""The user's preferences note from the page's "Help me start" (what matters most, horizon, comfort with price
swings, sectors). It is added to the run's question, so the screener, the coordinator and every agent after them
read it and the trace keeps it; `split` takes it off again for display."""
import re

TAG = re.compile(r"\s*<preferences>\n?(.*?)\n?</preferences>", re.DOTALL)


def attach(question: str, note: str | None) -> str:
    note = (note or "").strip()
    return f"{question}\n\n<preferences>\n{note}\n</preferences>" if note else question


def split(question: str | None) -> tuple[str | None, str | None]:
    """The question without its note, and the note (None if it has none)."""
    found = TAG.search(question or "")
    if not found:
        return question, None
    return (question[:found.start()] + question[found.end():]).strip(), found[1].strip() or None
