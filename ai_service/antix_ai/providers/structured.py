"""Robust structured (JSON) output for any chat model, including small local ones."""

from __future__ import annotations

import json
import logging
import re
from typing import TypeVar

from pydantic import BaseModel, ValidationError

from antix_ai.providers.base import ChatModel, Message, ProviderError, strip_think

logger = logging.getLogger(__name__)
T = TypeVar("T", bound=BaseModel)

_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)


class StructuredOutputError(ProviderError):
    pass


def extract_json(text: str) -> dict | list:
    """Find the first balanced JSON object/array in model output."""
    text = strip_think(text)
    if m := _FENCE_RE.search(text):
        text = m.group(1)
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    for open_ch, close_ch in (("{", "}"), ("[", "]")):
        start = text.find(open_ch)
        while start != -1:
            depth, in_str, esc = 0, False, False
            for i in range(start, len(text)):
                c = text[i]
                if in_str:
                    if esc:
                        esc = False
                    elif c == "\\":
                        esc = True
                    elif c == '"':
                        in_str = False
                elif c == '"':
                    in_str = True
                elif c == open_ch:
                    depth += 1
                elif c == close_ch:
                    depth -= 1
                    if depth == 0:
                        candidate = text[start : i + 1]
                        try:
                            return json.loads(_repair(candidate))
                        except json.JSONDecodeError:
                            break
            start = text.find(open_ch, start + 1)
    raise ValueError("no JSON found in model output")


def _repair(s: str) -> str:
    # trailing commas are the most common small-model mistake
    return re.sub(r",\s*([}\]])", r"\1", s)


async def complete_structured(
    model: ChatModel,
    messages: list[Message],
    schema: type[T],
    *,
    max_tokens: int = 800,
    retries: int = 1,
    usage_cb=None,
) -> T:
    """Call ``model`` and parse the reply into ``schema``; one corrective retry on failure."""
    msgs = list(messages)
    last_err: Exception | None = None
    for attempt in range(retries + 1):
        comp = await model.complete(msgs, max_tokens=max_tokens, temperature=0.0, json_mode=True)
        if usage_cb:
            usage_cb(comp.model, comp.prompt_tokens, comp.completion_tokens)
        try:
            return schema.model_validate(extract_json(comp.text))
        except (ValueError, ValidationError) as exc:
            last_err = exc
            logger.info("structured output invalid (attempt %d): %s", attempt + 1, str(exc)[:200])
            msgs = msgs + [
                Message("assistant", comp.text[:2000]),
                Message(
                    "user",
                    "That was not valid. Reply with ONLY a JSON object matching the schema. "
                    f"Error: {str(exc)[:300]}",
                ),
            ]
    raise StructuredOutputError(f"could not parse {schema.__name__}: {last_err}")
