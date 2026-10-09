"""Provider interfaces shared by every model backend."""

from __future__ import annotations

import re
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from typing import Literal, Protocol, runtime_checkable

import numpy as np

Role = Literal["system", "user", "assistant"]


class ProviderError(RuntimeError):
    """A model call failed after retries."""


class ProviderUnavailable(ProviderError):
    """No model is configured for this role (offline mode) -> callers use fallbacks."""


@dataclass(frozen=True)
class Message:
    role: Role
    content: str


@dataclass
class Completion:
    text: str
    model: str
    prompt_tokens: int = 0
    completion_tokens: int = 0


UsageCallback = Callable[[str, int, int], None]  # (model, prompt_tokens, completion_tokens)


@runtime_checkable
class ChatModel(Protocol):
    name: str

    async def complete(
        self,
        messages: list[Message],
        *,
        max_tokens: int = 1024,
        temperature: float | None = None,
        json_mode: bool = False,
    ) -> Completion: ...

    def stream(
        self,
        messages: list[Message],
        *,
        max_tokens: int = 1024,
        temperature: float | None = None,
        on_usage: UsageCallback | None = None,
    ) -> AsyncIterator[str]: ...


@runtime_checkable
class Embedder(Protocol):
    name: str
    dim: int

    async def embed(self, texts: list[str]) -> list[np.ndarray]: ...


@runtime_checkable
class Reranker(Protocol):
    name: str

    async def rerank(self, query: str, documents: list[str]) -> list[float] | None:
        """Return one relevance score per document, or None to keep the input order."""
        ...


_THINK_RE = re.compile(r"<think>.*?</think>\s*", re.DOTALL | re.IGNORECASE)


def strip_think(text: str) -> str:
    text = _THINK_RE.sub("", text)
    # Unterminated think block (truncated output): drop it entirely
    if "<think>" in text.lower():
        text = text[: text.lower().index("<think>")]
    return text.strip()


class ThinkStreamFilter:
    """Removes <think>...</think> spans from a token stream, across chunk boundaries."""

    OPEN, CLOSE = "<think>", "</think>"

    def __init__(self) -> None:
        self._buf = ""
        self._inside = False

    def feed(self, chunk: str) -> str:
        self._buf += chunk
        out: list[str] = []
        while self._buf:
            if self._inside:
                idx = self._buf.find(self.CLOSE)
                if idx == -1:
                    self._buf = self._buf[-(len(self.CLOSE) - 1):]
                    break
                self._buf = self._buf[idx + len(self.CLOSE):].lstrip()
                self._inside = False
            else:
                idx = self._buf.find(self.OPEN)
                if idx == -1:
                    # keep a tail that could be the start of "<think>"
                    safe = len(self._buf) - (len(self.OPEN) - 1)
                    if safe > 0:
                        out.append(self._buf[:safe])
                        self._buf = self._buf[safe:]
                    break
                out.append(self._buf[:idx])
                self._buf = self._buf[idx + len(self.OPEN):]
                self._inside = True
        return "".join(out)

    def flush(self) -> str:
        rest = "" if self._inside else self._buf
        self._buf = ""
        return rest
