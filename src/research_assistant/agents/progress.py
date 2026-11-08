"""Progress lines for a run's trace events: the CLI prints one per event as the run goes; the web page shows one entry
per model step, with its tool calls folded under it."""
from collections import Counter

from .tool_lines import STATUS, Seen, count, line, status

FOLDED = ("tool_call", "finish", "nudge")  # shown under their model step on the page


def describe(event: dict, seen: Seen | None = None) -> str | None:
    """One line for a trace event, or None for events not worth a line (e.g. run_start). Pass one `seen` for all of
    a run's events, so a tool line can name the company and period behind the IDs it was given."""
    seen = Seen() if seen is None else seen
    seen.add(event)
    if (text := _text(event, seen)) is None:
        return None
    if event["kind"] in ("model_call", *FOLDED) and event.get("step"):  # the host's own calls have no step
        text = f"step {event['step']}: {text}"
    who = f"[{event['agent']}] " if event.get("agent") else ""  # the role that did it (condition C)
    return who + text


def timeline(events: list[dict]) -> list[dict]:
    """The page's entries, with the role that wrote each. A model step's tool calls, answer and nudge fold under
    its entry, whose text sums them up: "Step 4 · 10 calculations · all OK"."""
    seen, entries, steps = Seen(), [], {}
    for event in events:
        seen.add(event)
        try:
            text, asked = _text(event, seen), _asked(event)
        except (KeyError, TypeError, ValueError, AttributeError):  # traces from before a field was added
            text, asked = event.get("kind"), []
        kind, role, step = event.get("kind"), event.get("agent"), steps.get(event.get("agent"))
        if kind in FOLDED and step and event.get("step") == step["step"]:  # an analyst's answer can come much later
            if text:
                step["details"].append({"seq": event.get("seq"), "text": text, "status": _state(event)})
            continue
        for over in steps.values() if kind == "run_end" else [step] if step else []:
            over["open"] = False  # the role moved on, so calls still without a result were never run
        if not text:
            continue
        entry = {"seq": event.get("seq"), "at": event.get("at"), "kind": kind, "role": role, "text": text}
        if kind == "model_call":
            steps[role] = entry | {"step": event.get("step"), "details": [], "asked": asked, "open": True}
            entry = steps[role]
        entries.append(entry)
    for entry in entries:
        if "asked" in entry:
            entry["text"] = _heading(entry, entry.pop("asked"), entry.pop("open"))
    return entries


def _text(event: dict, seen: Seen) -> str | None:
    kind = event["kind"]
    if kind == "plan":
        return "plan ready"
    if kind == "model_call":
        asked = _asked(event)
        tools = any(not name.startswith("submit_") for name in asked)  # submit_* hands in the answer
        return event.get("problem") or (f"{'asked for ' if tools else ''}{count(asked)}" if asked else
                                        "answered without calling a tool")
    if kind == "tool_call":
        return line(event, seen)
    if kind == "finish":
        return "Handing in the answer → " + ("OK" if event.get("valid") else
                                            "invalid: " + "; ".join(event.get("problems") or ["no reason given"]))
    if kind == "nudge":
        return "Reminded to call a tool or hand in its answer"
    if kind == "check":
        return f"checker: {len(event['flags'])} flags"
    if kind == "analyst_start":
        return ("follow-up: " if event["follow_up"] else "task: ") + " ".join(event["task"].split())
    if kind == "analyst_end":
        return f"done ({event['status']}): {event['findings']} findings"
    if kind == "critic_start":
        return f"review round {event['round']}"
    if kind == "objections":
        material = sum(1 for o in event["raised"] if o["material"])
        return (f"round {event['round']}: {len(event['raised'])} objections ({material} material), "
                f"{len(event['repeats'])} repeats")
    if kind == "revision_start":
        return f"revising for {len(event['objections'])} objections"
    if kind == "outcomes":
        return "outcomes: " + ", ".join(f"{o['objection']} {o['outcome']}" for o in event["outcomes"])
    if kind == "screen_spec":
        return "screen spec:" + "".join(f"\n  - {text}" for text in event["shown"])
    if kind == "questions":
        return (f"screen spec drafted, {len(event['terms'])} questions for the user:"
                + "".join(f"\n  - {text}" for text in event["shown"]))
    if kind == "clarify":
        return f"{event['term']}: " + (f"set to {event['answer']!r}" if event["answer"] else
                                       "proposal accepted" if event["answer"] == "" else "assumed (no answer)")
    if kind == "candidate":
        return f"candidate {event['rank']} {event['name']}: check {event['verdict']}"
    if kind == "research_start":
        return f"researching candidate {event['rank']} {event['name']}"
    if kind == "research_end":
        return f"research of candidate {event['rank']} {event['status']} (trace {event['trace']})"
    if kind == "injected":
        return f"injected {event['defect']}: {event['change']}"
    if kind in ("self_review", "stopped_at_limit", "cancelled", "error"):
        return kind.replace("_", " ") + (f": {event['error']}" if kind == "error" else "")
    return None


def _asked(event: dict) -> list[str]:
    return [c["function"]["name"] for c in event["tool_calls"]] if event.get("kind") == "model_call" else []


def _state(event: dict) -> str | None:
    """How a folded event ended, for its step's sum; a nudge isn't counted."""
    if event.get("kind") == "finish":
        return "ok" if event.get("valid") else "invalid"
    return status(event) if event.get("kind") == "tool_call" else None


def _heading(entry: dict, asked: list[str], still_open: bool) -> str:
    """"Step 4 · 10 calculations · 9 OK, 1 unsupported". A call with no result is still running (an analyst can
    take minutes) while the step is open; once its role moved on, or the run ended, it was never run."""
    states = Counter(d["status"] for d in entry["details"] if d["status"])
    waiting = len(asked) - sum(states.values())
    if states and set(states) == {"ok"} and waiting <= 0:
        outcome = "all OK" if states["ok"] > 1 else "OK"
    else:
        missing = f"{waiting} {'with no result yet' if still_open else 'not run'}" if waiting > 0 else None
        outcome = ", ".join([f"{n} {STATUS.get(s, s)}" for s, n in sorted(states.items(), key=lambda p: p[0] != "ok")]
                            + ([missing] if missing else []))
    step = f"Step {entry['step']}" if entry.get("step") is not None else "Step"
    return " · ".join(part for part in (step, count(asked) if asked else entry["text"], outcome) if part)
