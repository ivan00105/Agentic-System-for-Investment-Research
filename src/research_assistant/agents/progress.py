"""Progress lines for a run's trace events: the CLI prints them as the run goes, the web page lists them."""


def describe(event: dict) -> str | None:
    """One line for a trace event, or None for events not worth a line (e.g. run_start)."""
    kind, step = event["kind"], event.get("step")
    if kind == "plan":
        line = "plan ready"
    elif kind == "model_call":
        calls = [c["function"]["name"] for c in event["tool_calls"]]
        line = f"step {step}: model asks for {', '.join(calls) or 'no tool'}"
    elif kind == "tool_call":  # the host's own calls (Discover's screen and checks) have no step
        line = (f"step {step}: " if step else "") + f"{event['name']} -> {event['result']['status']}" + (
            " (repeat)" if event["repeat_of"] else "")
    elif kind == "check":
        line = f"checker: {len(event['flags'])} flags"
    elif kind == "analyst_start":
        line = ("follow-up: " if event["follow_up"] else "task: ") + " ".join(event["task"].split())
    elif kind == "analyst_end":
        line = f"done ({event['status']}): {event['findings']} findings"
    elif kind == "critic_start":
        line = f"review round {event['round']}"
    elif kind == "objections":
        material = sum(1 for o in event["raised"] if o["material"])
        line = (f"round {event['round']}: {len(event['raised'])} objections ({material} material), "
                f"{len(event['repeats'])} repeats")
    elif kind == "revision_start":
        line = f"revising for {len(event['objections'])} objections"
    elif kind == "outcomes":
        line = "outcomes: " + ", ".join(f"{o['objection']} {o['outcome']}" for o in event["outcomes"])
    elif kind == "screen_spec":
        line = "screen spec:" + "".join(f"\n  - {text}" for text in event["shown"])
    elif kind == "clarify":
        line = f"{event['term']}: " + (f"set to {event['answer']!r}" if event["answer"] else
                                       "proposal accepted" if event["answer"] == "" else "assumed (no answer)")
    elif kind == "candidate":
        line = f"candidate {event['rank']} {event['name']}: check {event['verdict']}"
    elif kind == "research_start":
        line = f"researching candidate {event['rank']} {event['name']}"
    elif kind == "research_end":
        line = f"research of candidate {event['rank']} {event['status']} (trace {event['trace']})"
    elif kind == "injected":
        line = f"injected {event['defect']}: {event['change']}"
    elif kind in ("self_review", "stopped_at_limit", "cancelled", "nudge", "error"):
        line = f"{kind.replace('_', ' ')}" + (f": {event['error']}" if kind == "error" else "")
    else:
        return None
    who = f"[{event['agent']}] " if event.get("agent") else ""  # the role that did it (condition C)
    return who + line

