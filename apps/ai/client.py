"""Typed HTTP client for the Antix AI service (ai_service/)."""

from __future__ import annotations

import json
import logging
from collections.abc import Iterator
from typing import Any

import requests
from django.conf import settings

logger = logging.getLogger(__name__)


class AIUnavailable(RuntimeError):
    """The AI service could not be reached or returned an error."""


class AIClient:
    def __init__(self, base_url: str | None = None, key: str | None = None, timeout: float | None = None):
        self.base = (base_url or settings.AI_SERVICE_URL).rstrip("/")
        self.key = key or settings.AI_SERVICE_KEY
        self.timeout = timeout or settings.AI_SERVICE_TIMEOUT
        if not self.key:
            raise AIUnavailable("AI_SERVICE_KEY is not configured")

    @property
    def _headers(self) -> dict[str, str]:
        return {"X-Service-Key": self.key}

    def _request(self, method: str, path: str, **kw: Any) -> Any:
        try:
            resp = requests.request(
                method, f"{self.base}{path}", headers=self._headers, timeout=kw.pop("timeout", self.timeout), **kw
            )
            resp.raise_for_status()
            return resp.json()
        except requests.RequestException as exc:
            raise AIUnavailable(str(exc)) from exc

    # ---------------------------------------------------------------- chat

    def ask(self, query: str, session_id: str | None = None, timezone: str | None = None) -> dict:
        return self._request(
            "POST", "/v1/ask/sync", json={"query": query, "session_id": session_id, "timezone": timezone},
            timeout=self.timeout,
        )

    def ask_stream(self, query: str, session_id: str | None = None, timezone: str | None = None) -> Iterator[bytes]:
        """Yield raw SSE bytes from the service (for proxying to the browser)."""
        try:
            resp = requests.post(
                f"{self.base}/v1/ask",
                headers=self._headers,
                json={"query": query, "session_id": session_id, "timezone": timezone, "stream": True},
                stream=True,
                timeout=(5, self.timeout),
            )
            resp.raise_for_status()
        except requests.RequestException as exc:
            raise AIUnavailable(str(exc)) from exc
        return resp.iter_content(chunk_size=None)

    def conversation(self, session_id: str) -> list[dict]:
        return self._request("GET", f"/v1/conversations/{session_id}", timeout=10)["messages"]

    def feedback(self, trace_id: str, rating: int, note: str | None = None) -> None:
        self._request("POST", "/v1/feedback", json={"trace_id": trace_id, "rating": rating, "note": note}, timeout=10)

    # ------------------------------------------------------------ ingestion

    def ingest(self, post_id: int, force: bool = False) -> dict:
        return self._request("POST", f"/v1/ingest/{post_id}", params={"force": str(force).lower()}, timeout=15)

    def reconcile(self, days: int | None = None, force: bool = False) -> dict:
        return self._request("POST", "/v1/ingest/reconcile", json={"days": days, "force": force}, timeout=15)

    # ------------------------------------------------------------- content

    def briefing(self, range_text: str = "today", tz: str | None = None) -> dict:
        return self._request("GET", "/v1/briefing", params={"range": range_text, "tz": tz}, timeout=15)

    def related(self, post_id: int, limit: int = 6) -> list[dict]:
        return self._request("GET", f"/v1/posts/{post_id}/related", params={"limit": limit}, timeout=10)["related"]

    def shadow(self, query: str, answer: str, cited_post_ids: list[int], latency_ms: float) -> None:
        self._request(
            "POST", "/v1/shadow",
            json={"query": query, "answer": answer, "cited_post_ids": cited_post_ids, "latency_ms": latency_ms},
            timeout=10,
        )


def parse_sse(chunks: Iterator[bytes]) -> Iterator[dict]:
    """Parse an SSE byte stream into event dicts (used by tests and the stream proxy)."""
    buf = b""
    for chunk in chunks:
        buf += chunk
        while b"\n\n" in buf:
            raw, buf = buf.split(b"\n\n", 1)
            for line in raw.decode("utf-8", "replace").splitlines():
                if line.startswith("data: ") and line[6:].strip() not in ("", "{}"):
                    try:
                        yield json.loads(line[6:])
                    except json.JSONDecodeError:
                        logger.warning("bad SSE payload: %s", line[:200])
