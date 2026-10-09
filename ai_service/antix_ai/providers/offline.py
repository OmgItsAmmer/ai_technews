"""Offline providers: no network, deterministic.

* ``OfflineChat`` raises ProviderUnavailable, so every pipeline stage uses its
  deterministic fallback (heuristic planner, extractive answers, rule-based checks).
* ``HashingEmbedder`` is a feature-hashing bag of words + bigrams. Not a semantic
  model, but stable and good enough for tests, CI evals and local development.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import AsyncIterator

import numpy as np

from antix_ai.providers.base import Completion, Message, ProviderUnavailable, UsageCallback

_TOKEN_RE = re.compile(r"[a-z0-9][a-z0-9.+#-]*")
STOPWORDS = frozenset(
    """a an and are as at be been but by can could did do does for from had has have how i if in
    into is it its me more most my no not of on or our out so than that the their them then there
    these they this those to up us was we were what when where which who whom why will with would
    you your about after again all also any because before being between both during each few
    further here just new now only other over same should some such through under until very via
    tell know get give latest news""".split()
)


def tokenize(text: str) -> list[str]:
    toks = _TOKEN_RE.findall(text.lower())
    return [_stem(t.strip(".-")) for t in toks if t not in STOPWORDS and len(t) > 1]


def _stem(tok: str) -> str:
    for suf in ("ing", "ies", "es", "ed", "s"):
        if len(tok) > len(suf) + 3 and tok.endswith(suf):
            return tok[: -len(suf)] + ("y" if suf == "ies" else "")
    return tok


class HashingEmbedder:
    def __init__(self, dim: int):
        self.dim = dim
        self.name = f"hashing-{dim}"

    def _vec(self, text: str) -> np.ndarray:
        v = np.zeros(self.dim, dtype=np.float32)
        toks = tokenize(text)
        feats = toks + [f"{a}_{b}" for a, b in zip(toks, toks[1:], strict=False)]
        for f in feats:
            h = int.from_bytes(hashlib.blake2b(f.encode(), digest_size=8).digest(), "little")
            v[h % self.dim] += 1.0 if (h >> 63) & 1 else -1.0
        n = np.linalg.norm(v)
        return v / n if n else v

    async def embed(self, texts: list[str]) -> list[np.ndarray]:
        return [self._vec(t) for t in texts]


class OfflineChat:
    def __init__(self, name: str = "offline"):
        self.name = name

    async def complete(
        self,
        messages: list[Message],
        *,
        max_tokens: int = 1024,
        temperature: float | None = None,
        json_mode: bool = False,
    ) -> Completion:
        raise ProviderUnavailable("offline mode")

    async def stream(
        self,
        messages: list[Message],
        *,
        max_tokens: int = 1024,
        temperature: float | None = None,
        on_usage: UsageCallback | None = None,
    ) -> AsyncIterator[str]:
        raise ProviderUnavailable("offline mode")
        yield ""  # pragma: no cover  (makes this an async generator)
