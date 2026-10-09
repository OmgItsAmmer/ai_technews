"""Rerankers: HTTP cross-encoder (TEI / Cohere / Jina format), LLM listwise, or none."""

from __future__ import annotations

import logging

import httpx
from pydantic import BaseModel

from antix_ai.providers.base import ChatModel, Message, ProviderError
from antix_ai.providers.structured import complete_structured

logger = logging.getLogger(__name__)


class NoReranker:
    name = "none"

    async def rerank(self, query: str, documents: list[str]) -> list[float] | None:
        return None


class HttpReranker:
    """Works with HuggingFace TEI (/rerank: {query, texts}) and Cohere/Jina ({query, documents})."""

    def __init__(self, url: str, api_key: str | None = None, model: str | None = None):
        self.url = url
        self.model = model
        self.name = f"http:{model or url}"
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        self.client = httpx.AsyncClient(timeout=10.0, headers=headers)

    async def rerank(self, query: str, documents: list[str]) -> list[float] | None:
        if not documents:
            return []
        payload: dict = {"query": query, "texts": documents, "documents": documents}
        if self.model:
            payload["model"] = self.model
            payload["top_n"] = len(documents)
        try:
            resp = await self.client.post(self.url, json=payload)
            resp.raise_for_status()
            data = resp.json()
        except httpx.HTTPError as exc:
            raise ProviderError(f"rerank failed: {exc}") from exc
        items = data.get("results", data) if isinstance(data, dict) else data
        scores = [0.0] * len(documents)
        for item in items:
            idx = item["index"]
            scores[idx] = float(item.get("relevance_score", item.get("score", 0.0)))
        return scores


class _Ranking(BaseModel):
    ranking: list[int]


class LLMReranker:
    """Listwise reranking with the fast model. Cheap for <=30 short passages."""

    def __init__(self, model: ChatModel, max_chars: int = 500):
        self.model = model
        self.max_chars = max_chars
        self.name = f"llm:{model.name}"

    async def rerank(self, query: str, documents: list[str]) -> list[float] | None:
        if len(documents) <= 1:
            return [1.0] * len(documents)
        numbered = "\n".join(
            f"[{i}] {d[: self.max_chars].replace(chr(10), ' ')}" for i, d in enumerate(documents)
        )
        msgs = [
            Message(
                "system",
                "You rank news passages by how directly they help answer a question. "
                'Return JSON: {"ranking": [passage numbers, most relevant first]}. '
                "Omit passages that are irrelevant.",
            ),
            Message("user", f"Question: {query}\n\nPassages:\n{numbered}"),
        ]
        result = await complete_structured(self.model, msgs, _Ranking, max_tokens=300)
        n = len(documents)
        scores = [0.0] * n
        seen: set[int] = set()
        ranked = [i for i in result.ranking if 0 <= i < n and not (i in seen or seen.add(i))]
        for pos, idx in enumerate(ranked):
            scores[idx] = 1.0 - pos / (len(ranked) + 1)
        return scores
