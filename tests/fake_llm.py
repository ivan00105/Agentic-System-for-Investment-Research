"""A scripted stand-in for the OpenAI client: no network, but real SDK response types."""
import itertools
import json
from types import SimpleNamespace

from openai.types.chat import ChatCompletion

_call_ids = itertools.count(1)


def reply(content: str | None = None, tool_calls=(), usage=(10, 5), extra: dict | None = None) -> ChatCompletion:
    """One model answer. `tool_calls` holds (name, arguments) pairs; a str argument is sent as-is (bad JSON)."""
    calls = [{"id": f"call_{next(_call_ids)}", "type": "function",
              "function": {"name": name, "arguments": args if isinstance(args, str) else json.dumps(args)}}
             for name, args in tool_calls]
    message = {"role": "assistant", "content": content, "tool_calls": calls or None, **(extra or {})}
    return ChatCompletion.model_validate({
        "id": "fake", "object": "chat.completion", "created": 0, "model": "fake-model",
        "choices": [{"index": 0, "finish_reason": "tool_calls" if calls else "stop", "message": message}],
        "usage": {"prompt_tokens": usage[0], "completion_tokens": usage[1], "total_tokens": sum(usage)}})


def tool_results(messages: list[dict]) -> list[dict]:
    """Every tool result sent to the model so far, oldest first (finish acknowledgements skipped)."""
    return [json.loads(m["content"]) for m in messages if m["role"] == "tool" and m["content"].startswith("{")]


class FakeClient:
    """Answers `chat.completions.create` from a script. A step is a ChatCompletion, an exception to
    raise, or a function of the messages so far (to cite IDs that earlier tool results returned)."""

    def __init__(self, *script):
        self.script = list(script)
        self.requests: list[dict] = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))

    def create(self, **kwargs):
        self.requests.append({**kwargs, "messages": list(kwargs["messages"])})
        if not self.script:
            raise AssertionError("The scripted model ran out of answers.")
        step = self.script.pop(0)
        if isinstance(step, Exception):
            raise step
        return step(kwargs["messages"]) if callable(step) else step
