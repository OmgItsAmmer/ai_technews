"""Anthropic Messages API chat provider."""

from __future__ import annotations

from collections.abc import AsyncIterator

import anthropic
from anthropic import AsyncAnthropic

from antix_ai.config import ModelRole
from antix_ai.providers.base import Completion, Message, ProviderError, UsageCallback


def _split(messages: list[Message]) -> tuple[str, list[dict]]:
    system = "\n\n".join(m.content for m in messages if m.role == "system")
    convo = [{"role": m.role, "content": m.content} for m in messages if m.role != "system"]
    return system, convo


class AnthropicChat:
    def __init__(self, role: ModelRole):
        self.role = role
        self.name = role.model
        self.client = AsyncAnthropic(
            api_key=role.api_key.get_secret_value() if role.api_key else None,
            base_url=role.base_url or None,
            timeout=role.timeout_s,
            max_retries=role.max_retries,
        )

    async def complete(
        self,
        messages: list[Message],
        *,
        max_tokens: int = 1024,
        temperature: float | None = None,
        json_mode: bool = False,
    ) -> Completion:
        system, convo = _split(messages)
        if json_mode:
            system += "\n\nRespond with a single valid JSON object and nothing else."
        try:
            resp = await self.client.messages.create(
                model=self.role.model,
                system=system,
                messages=convo,
                max_tokens=max_tokens,
                temperature=self.role.temperature if temperature is None else temperature,
            )
        except anthropic.AnthropicError as exc:
            raise ProviderError(str(exc)) from exc
        text = "".join(b.text for b in resp.content if getattr(b, "type", "") == "text")
        return Completion(
            text=text.strip(),
            model=resp.model,
            prompt_tokens=resp.usage.input_tokens,
            completion_tokens=resp.usage.output_tokens,
        )

    async def stream(
        self,
        messages: list[Message],
        *,
        max_tokens: int = 1024,
        temperature: float | None = None,
        on_usage: UsageCallback | None = None,
    ) -> AsyncIterator[str]:
        system, convo = _split(messages)
        try:
            async with self.client.messages.stream(
                model=self.role.model,
                system=system,
                messages=convo,
                max_tokens=max_tokens,
                temperature=self.role.temperature if temperature is None else temperature,
            ) as s:
                async for text in s.text_stream:
                    yield text
                final = await s.get_final_message()
                if on_usage:
                    on_usage(final.model, final.usage.input_tokens, final.usage.output_tokens)
        except anthropic.AnthropicError as exc:
            raise ProviderError(str(exc)) from exc
