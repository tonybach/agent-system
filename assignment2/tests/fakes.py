"""Test doubles that mimic the parts of the openai client the harness uses."""

import copy
import json
from types import SimpleNamespace


class RateLimitError(Exception):
    pass


class BadRequestError(Exception):
    def __init__(self, msg, status_code=400):
        super().__init__(msg)
        self.status_code = status_code


def tool_call(name, args, call_id=None):
    raw = args if isinstance(args, str) else json.dumps(args)
    return SimpleNamespace(id=call_id, type="function", function=SimpleNamespace(name=name, arguments=raw))


def response(content="", tool_calls=None, prompt_tokens=100, completion_tokens=10, finish_reason=None,
             reasoning_content=None, usage=True):
    msg = SimpleNamespace(role="assistant", content=content, tool_calls=tool_calls or None,
                          reasoning_content=reasoning_content)
    fr = finish_reason or ("tool_calls" if tool_calls else "stop")
    u = SimpleNamespace(prompt_tokens=prompt_tokens, completion_tokens=completion_tokens,
                        total_tokens=prompt_tokens + completion_tokens) if usage else None
    return SimpleNamespace(choices=[SimpleNamespace(message=msg, finish_reason=fr)], usage=u)


class FakeClient:
    """Returns scripted responses (or raises scripted exceptions) in order.

    A script item may be a callable taking the messages and returning a response.
    Every request's messages are deep-copied into ``self.requests``.
    """

    def __init__(self, script):
        self.script = list(script)
        self.requests = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, model, messages, tools=None, **kwargs):
        self.requests.append(copy.deepcopy(messages))
        if not self.script:
            raise AssertionError("FakeClient script exhausted")
        item = self.script.pop(0)
        if callable(item) and not isinstance(item, SimpleNamespace):
            item = item(messages)
        if isinstance(item, Exception):
            raise item
        return item


class NullLogger:
    def __init__(self):
        self.events = []

    def __getattr__(self, name):
        def record(*args, **kwargs):
            self.events.append((name, args, kwargs))
        return record
