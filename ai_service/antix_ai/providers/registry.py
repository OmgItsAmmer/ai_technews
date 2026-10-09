"""Build providers from settings; wrap with fallbacks."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from dataclasses import dataclass

from antix_ai.config import ModelRole, Settings
from antix_ai.providers.anthropic_provider import AnthropicChat
from antix_ai.providers.base import (
    ChatModel,
    Completion,
    Embedder,
    Message,
    ProviderError,
    ProviderUnavailable,
    Reranker,
    UsageCallback,
)
from antix_ai.providers.offline import HashingEmbedder, OfflineChat
from antix_ai.providers.openai_compat import OpenAIChat, OpenAIEmbedder
from antix_ai.providers.rerank import HttpReranker, LLMReranker, NoReranker

logger = logging.getLogger(__name__)


def build_chat(role: ModelRole) -> ChatModel:
    if role.provider == "openai":
        return OpenAIChat(role)
    if role.provider == "anthropic":
        return AnthropicChat(role)
    return OfflineChat()


class FallbackChat:
    """Try ``primary``; on failure use ``secondary``. Streaming falls back only before
    the first token, so users never see a half answer spliced with another model."""

    def __init__(self, primary: ChatModel, secondary: ChatModel):
        self.primary, self.secondary = primary, secondary
        self.name = f"{primary.name}|{secondary.name}"

    async def complete(self, messages: list[Message], **kw) -> Completion:
        try:
            return await self.primary.complete(messages, **kw)
        except ProviderError as exc:
            logger.warning("primary model %s failed: %s; falling back", self.primary.name, exc)
            return await self.secondary.complete(messages, **kw)

    async def stream(
        self, messages: list[Message], *, on_usage: UsageCallback | None = None, **kw
    ) -> AsyncIterator[str]:
        started = False
        try:
            async for tok in self.primary.stream(messages, on_usage=on_usage, **kw):
                started = True
                yield tok
            return
        except ProviderError as exc:
            if started:
                raise
            logger.warning("primary stream %s failed: %s; falling back", self.primary.name, exc)
        async for tok in self.secondary.stream(messages, on_usage=on_usage, **kw):
            yield tok


def build_embedder(s: Settings) -> Embedder:
    if s.embed_provider == "offline":
        return HashingEmbedder(s.embed_dim)
    key = s.embed_api_key.get_secret_value() if s.embed_api_key else None
    return OpenAIEmbedder(s.embed_model, s.embed_dim, s.embed_base_url, key, s.embed_batch_size)


def build_reranker(s: Settings, fast: ChatModel) -> Reranker:
    if s.rerank == "http" and s.rerank_url:
        key = s.rerank_api_key.get_secret_value() if s.rerank_api_key else None
        return HttpReranker(s.rerank_url, key, s.rerank_model)
    if s.rerank == "llm" and not isinstance(fast, OfflineChat):
        return LLMReranker(fast)
    return NoReranker()


@dataclass
class Providers:
    fast: ChatModel
    strong: ChatModel
    embedder: Embedder
    reranker: Reranker

    @property
    def offline(self) -> bool:
        return isinstance(self.strong, OfflineChat)


def build_providers(s: Settings) -> Providers:
    fast = build_chat(s.fast)
    strong = build_chat(s.strong)
    if s.strong_fallback is not None:
        strong = FallbackChat(strong, build_chat(s.strong_fallback))
    return Providers(
        fast=fast,
        strong=strong,
        embedder=build_embedder(s),
        reranker=build_reranker(s, fast),
    )


__all__ = ["Providers", "build_providers", "ProviderUnavailable", "FallbackChat"]
