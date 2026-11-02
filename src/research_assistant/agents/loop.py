"""A generic Chat Completions tool-calling loop over tools/registry.py (PROJECT_GUIDE §2, REFERENCE §2).

The model picks a tool and fills in its arguments; the host runs it and records every step in the trace.
The loop ends when the model calls the finish tool with valid arguments. Reaching the step guard asks the
model once for its best answer and returns it marked "stopped_at_limit"; nothing here raises.
"""
import json
from dataclasses import dataclass
from typing import Literal

from openai import OpenAIError
from pydantic import BaseModel, ValidationError

from .. import config
from ..model_access import safe_model_error
from ..tools import registry
from ..tools.result import ToolContext, ToolResult
from .trace import Trace


@dataclass(frozen=True)
class Finish:
    """The tool the model calls to hand in its answer; the arguments are validated against `model`."""

    name: str
    description: str
    model: type[BaseModel]

    def schema(self) -> dict:
        return {"type": "function", "function": {
            "name": self.name, "description": self.description, "parameters": self.model.model_json_schema()}}


@dataclass
class LoopResult:
    status: Literal["finished", "stopped_at_limit", "failed"]
    output: BaseModel | None  # the validated finish arguments, if the model handed any in
    steps: int  # model calls used
    error: str | None = None


def run_loop(client, model: str, request_kwargs: dict, messages: list[dict], context: ToolContext, finish: Finish,
             trace: Trace, *, tool_names: list[str] | None = None, max_steps: int = config.AGENT_MAX_STEPS) -> LoopResult:
    """Ask, run the requested tools, repeat. `messages` grows in place, so a caller can continue the
    same conversation later (e.g. to send checker flags back)."""
    tools = registry.schemas(tool_names) + [finish.schema()]
    seen: dict[str, tuple[int, ToolResult]] = {}
    steps = 0
    try:
        while steps < max_steps:
            steps += 1
            message = _ask(client, model, request_kwargs, messages, tools, trace, steps)
            if message is None or not message.tool_calls:
                messages.append({"role": "user", "content": f"Call a tool, or call {finish.name} to hand in your answer."})
                trace.write("nudge", step=steps)
                continue
            output = None
            for call in message.tool_calls:
                if call.function.name == finish.name:
                    output = _finish(call, finish, messages, trace, steps) or output
                else:
                    _run_tool(call, context, messages, trace, steps, seen)
            if output is not None:
                return LoopResult("finished", output, steps)
    except (OpenAIError, TimeoutError) as exc:
        return _failed(exc, trace, steps)
    return _finalize(client, model, request_kwargs, messages, tools, finish, trace, steps, max_steps)


def _finalize(client, model, request_kwargs, messages, tools, finish, trace, steps, max_steps) -> LoopResult:
    """The step guard was reached: one call that must use the finish tool, for the best partial answer."""
    trace.write("stopped_at_limit", step=steps, max_steps=max_steps)
    messages.append({"role": "user", "content": (
        f"The step limit ({max_steps} model calls) is reached, so no more tools will run. Call {finish.name} now "
        "with the best answer the evidence so far supports, and say what is missing.")})
    steps += 1
    try:
        message = _ask(client, model, request_kwargs, messages, tools, trace, steps,
                       tool_choice={"type": "function", "function": {"name": finish.name}})
    except (OpenAIError, TimeoutError) as exc:
        result = _failed(exc, trace, steps)
        return LoopResult("stopped_at_limit", None, steps, result.error)
    output = None
    for call in (message.tool_calls if message else None) or []:
        if call.function.name == finish.name:
            output = _finish(call, finish, messages, trace, steps) or output
        else:  # every tool call needs an answer, or the conversation can't continue
            messages.append({"role": "tool", "tool_call_id": call.id, "content": "Not run: the step limit is reached."})
    return LoopResult("stopped_at_limit", output, steps)


def _ask(client, model, request_kwargs, messages, tools, trace, step, **extra):
    # No max_tokens: output-token caps cut reasoning models off mid-answer (PROJECT_GUIDE §5).
    response = client.chat.completions.create(model=model, messages=messages, tools=tools, **request_kwargs, **extra)
    usage = response.usage.model_dump() if response.usage else None
    if not response.choices:
        trace.write("model_call", step=step, content=None, tool_calls=[], finish_reason=None, model=response.model,
                    usage=usage, problem="The provider returned no message.")
        return None
    choice = response.choices[0]
    message = choice.message
    entry = {"role": "assistant", "content": message.content}
    if message.tool_calls:
        entry["tool_calls"] = [{"id": c.id, "type": "function",
                                "function": {"name": c.function.name, "arguments": c.function.arguments}}
                               for c in message.tool_calls]
    if details := (message.model_extra or {}).get("reasoning_details"):
        entry["reasoning_details"] = details  # sent back so reasoning models can continue; not traced
    messages.append(entry)
    trace.write("model_call", step=step, content=message.content, tool_calls=entry.get("tool_calls", []),
                finish_reason=choice.finish_reason, model=response.model, usage=usage)
    return message


def _run_tool(call, context, messages, trace, step, seen):
    name, raw = call.function.name, call.function.arguments or "{}"
    repeat_of = None
    try:
        arguments = json.loads(raw)
        if not isinstance(arguments, dict):
            raise ValueError
    except ValueError:
        arguments = raw
        result = ToolResult(status="invalid", source="agent loop", warnings=[f"Arguments are not a JSON object: {raw}"])
    else:
        key = name + json.dumps(arguments, sort_keys=True)
        if key in seen:  # REFERENCE §2: a repeated action with no new inputs is skipped
            repeat_of, earlier = seen[key]
            result = earlier.model_copy(update={"warnings": [
                *earlier.warnings, f"Repeated call: same arguments as step {repeat_of}, so it was not run again."]})
        else:
            result = registry.call(name, arguments, context)
            seen[key] = (step, result)
    messages.append({"role": "tool", "tool_call_id": call.id, "content": result.model_dump_json()})
    trace.write("tool_call", step=step, name=name, arguments=arguments, repeat_of=repeat_of,
                result=result.model_dump(mode="json"))


def _finish(call, finish, messages, trace, step):
    try:
        output = finish.model.model_validate_json(call.function.arguments or "{}")
    except ValidationError as exc:
        problems = [f"{'.'.join(str(p) for p in e['loc']) or 'arguments'}: {e['msg']}" for e in exc.errors()]
        messages.append({"role": "tool", "tool_call_id": call.id,
                         "content": json.dumps({"status": "invalid", "warnings": problems})})
        trace.write("finish", step=step, valid=False, problems=problems, arguments=call.function.arguments)
        return None
    messages.append({"role": "tool", "tool_call_id": call.id, "content": "Submitted."})
    trace.write("finish", step=step, valid=True, output=output.model_dump(mode="json"))
    return output


def _failed(exc, trace, steps) -> LoopResult:
    error = str(safe_model_error(exc))
    trace.write("error", step=steps, error=error, type=type(exc).__name__)
    return LoopResult("failed", None, steps, error)
