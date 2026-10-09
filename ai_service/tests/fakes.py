"""Scripted chat model for testing LLM-dependent code paths without a network."""

from __future__ import annotations

import json
import re
from collections.abc import AsyncIterator, Callable

from antix_ai.providers.base import Completion, Message


class ScriptedChat:
    """Routes by the system prompt: handlers receive (system, user) and return text."""

    def __init__(self, name: str = "scripted", handlers: dict[str, Callable[[str, str], str]] | None = None):
        self.name = name
        self.handlers = handlers or {}
        self.calls: list[tuple[str, str]] = []

    def _reply(self, messages: list[Message]) -> str:
        system = next((m.content for m in messages if m.role == "system"), "")
        user = messages[-1].content
        self.calls.append((system, user))
        for key, fn in self.handlers.items():
            if key in system:
                return fn(system, user)
        return "{}"

    async def complete(self, messages, *, max_tokens=1024, temperature=None, json_mode=False) -> Completion:
        return Completion(self._reply(messages), self.name, 10, 10)

    async def stream(self, messages, *, max_tokens=1024, temperature=None, on_usage=None) -> AsyncIterator[str]:
        text = self._reply(messages)
        for i in range(0, len(text), 12):
            yield text[i : i + 12]
        if on_usage:
            on_usage(self.name, 100, len(text) // 4)


def planner(intent="fact_lookup", queries=None, entities=None, time_expression=None, sources=None):
    def handler(system: str, user: str) -> str:
        return json.dumps({
            "intent": intent, "search_queries": queries or [user], "entities": entities or [],
            "compare_targets": [], "sources": sources or [], "time_expression": time_expression,
            "answer_shape": "paragraph",
        })
    return handler


def answerer(text: str):
    return lambda system, user: text


def sids_in(user_prompt: str) -> list[str]:
    return re.findall(r"^\[(S\d+)\]", user_prompt, re.M)
