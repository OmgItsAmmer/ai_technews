"""OpenAI-compatible chat + embeddings (OpenAI, vLLM, Ollama, SGLang, LM Studio, ...)."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator

import numpy as np
import openai
from openai import AsyncOpenAI

from antix_ai.config import ModelRole
from antix_ai.providers.base import (
    Completion,
    Message,
    ProviderError,
    ThinkStreamFilter,
    UsageCallback,
    strip_think,
)

logger = logging.getLogger(__name__)


def _client(base_url: str | None, api_key: str | None, timeout: float, retries: int) -> AsyncOpenAI:
    return AsyncOpenAI(
        base_url=base_url or None,
        api_key=api_key or "not-needed",  # local servers usually ignore the key
        timeout=timeout,
        max_retries=retries,
    )


class OpenAIChat:
    def __init__(self, role: ModelRole):
        self.role = role
        self.name = role.model
        key = role.api_key.get_secret_value() if role.api_key else None
        self.client = _client(role.base_url, key, role.timeout_s, role.max_retries)
        self._json_mode_supported = True
        self._stream_usage_supported = True

    def _extra(self) -> dict:
        if self.role.disable_thinking:
            return {"extra_body": {"chat_template_kwargs": {"enable_thinking": False}}}
        return {}

    async def complete(
        self,
        messages: list[Message],
        *,
        max_tokens: int = 1024,
        temperature: float | None = None,
        json_mode: bool = False,
    ) -> Completion:
        kwargs = dict(
            model=self.role.model,
            messages=[{"role": m.role, "content": m.content} for m in messages],
            max_tokens=max_tokens,
            temperature=self.role.temperature if temperature is None else temperature,
            **self._extra(),
        )
        if json_mode and self._json_mode_supported:
            kwargs["response_format"] = {"type": "json_object"}
        try:
            resp = await self.client.chat.completions.create(**kwargs)
        except openai.BadRequestError as exc:
            if "response_format" not in kwargs:
                raise ProviderError(str(exc)) from exc
            # Some local servers reject response_format; remember and retry without it
            logger.info("server rejected response_format; disabling json mode for %s", self.name)
            self._json_mode_supported = False
            kwargs.pop("response_format")
            try:
                resp = await self.client.chat.completions.create(**kwargs)
            except openai.OpenAIError as exc2:
                raise ProviderError(str(exc2)) from exc2
        except openai.OpenAIError as exc:
            raise ProviderError(str(exc)) from exc

        text = strip_think(resp.choices[0].message.content or "")
        usage = resp.usage
        return Completion(
            text=text,
            model=resp.model or self.name,
            prompt_tokens=getattr(usage, "prompt_tokens", 0) or 0,
            completion_tokens=getattr(usage, "completion_tokens", 0) or 0,
        )

    async def stream(
        self,
        messages: list[Message],
        *,
        max_tokens: int = 1024,
        temperature: float | None = None,
        on_usage: UsageCallback | None = None,
    ) -> AsyncIterator[str]:
        kwargs = dict(
            model=self.role.model,
            messages=[{"role": m.role, "content": m.content} for m in messages],
            max_tokens=max_tokens,
            temperature=self.role.temperature if temperature is None else temperature,
            stream=True,
            **self._extra(),
        )
        if self._stream_usage_supported:
            kwargs["stream_options"] = {"include_usage": True}
        try:
            resp = await self.client.chat.completions.create(**kwargs)
        except openai.BadRequestError as exc:
            if "stream_options" not in kwargs:
                raise ProviderError(str(exc)) from exc
            self._stream_usage_supported = False
            kwargs.pop("stream_options")
            try:
                resp = await self.client.chat.completions.create(**kwargs)
            except openai.OpenAIError as exc2:
                raise ProviderError(str(exc2)) from exc2
        except openai.OpenAIError as exc:
            raise ProviderError(str(exc)) from exc

        flt = ThinkStreamFilter()
        try:
            async for event in resp:
                if event.usage and on_usage:
                    on_usage(
                        event.model or self.name,
                        event.usage.prompt_tokens or 0,
                        event.usage.completion_tokens or 0,
                    )
                if not event.choices:
                    continue
                delta = event.choices[0].delta.content or ""
                if delta and (out := flt.feed(delta)):
                    yield out
        except openai.OpenAIError as exc:
            raise ProviderError(str(exc)) from exc
        if tail := flt.flush():
            yield tail


class OpenAIEmbedder:
    def __init__(
        self,
        model: str,
        dim: int,
        base_url: str | None,
        api_key: str | None,
        batch_size: int = 64,
    ):
        self.name = model
        self.dim = dim
        self.batch_size = batch_size
        self.client = _client(base_url, api_key, 60.0, 3)
        # Only text-embedding-3* supports server-side dimension reduction
        self._send_dims = model.startswith("text-embedding-3")

    async def embed(self, texts: list[str]) -> list[np.ndarray]:
        out: list[np.ndarray] = []
        for i in range(0, len(texts), self.batch_size):
            batch = [t if t.strip() else " " for t in texts[i : i + self.batch_size]]
            kwargs = {"model": self.name, "input": batch}
            if self._send_dims:
                kwargs["dimensions"] = self.dim
            try:
                resp = await self.client.embeddings.create(**kwargs)
            except openai.OpenAIError as exc:
                raise ProviderError(f"embedding failed: {exc}") from exc
            for item in sorted(resp.data, key=lambda d: d.index):
                v = np.asarray(item.embedding, dtype=np.float32)
                if v.shape[0] != self.dim:
                    raise ProviderError(
                        f"embedding dim {v.shape[0]} != AI_EMBED_DIM {self.dim}; "
                        "fix config or re-run migrations for the new dimension"
                    )
                n = np.linalg.norm(v)
                out.append(v / n if n else v)
        return out
