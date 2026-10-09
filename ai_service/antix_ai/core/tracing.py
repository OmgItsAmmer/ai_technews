"""Per-request traces: stage timings, plan, evidence, verdicts. Persisted to ai.trace."""

from __future__ import annotations

import json
import logging
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any

from antix_ai.core.logging import trace_id_var

logger = logging.getLogger(__name__)


@dataclass
class Trace:
    kind: str
    query: str = ""
    session_id: str | None = None
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    started: float = field(default_factory=time.perf_counter)
    stages: dict[str, float] = field(default_factory=dict)
    data: dict[str, Any] = field(default_factory=dict)
    usage: list[dict[str, Any]] = field(default_factory=list)
    error: str | None = None

    def __post_init__(self) -> None:
        trace_id_var.set(self.id)

    @contextmanager
    def stage(self, name: str):
        t0 = time.perf_counter()
        try:
            yield
        finally:
            self.stages[name] = round((time.perf_counter() - t0) * 1000, 1)

    def mark(self, name: str) -> None:
        """Record elapsed ms since trace start (e.g. first_token)."""
        self.stages[name] = round((time.perf_counter() - self.started) * 1000, 1)

    def set(self, **kwargs: Any) -> None:
        self.data.update(kwargs)

    def add_usage(self, role: str, model: str, prompt_tokens: int, completion_tokens: int) -> None:
        self.usage.append(
            {"role": role, "model": model, "in": prompt_tokens, "out": completion_tokens}
        )

    @property
    def total_ms(self) -> float:
        return round((time.perf_counter() - self.started) * 1000, 1)


async def persist_trace(db, trace: Trace) -> None:
    """Best-effort: tracing must never fail a request."""
    try:
        await db.execute(
            """
            INSERT INTO ai.trace (id, kind, session_id, query, plan, retrieved, answer,
                                  verdict, grounding, latency, usage, error, backend)
            VALUES (%(id)s, %(kind)s, %(session_id)s, %(query)s, %(plan)s, %(retrieved)s,
                    %(answer)s, %(verdict)s, %(grounding)s, %(latency)s, %(usage)s,
                    %(error)s, %(backend)s)
            ON CONFLICT (id) DO NOTHING
            """,
            {
                "id": trace.id,
                "kind": trace.kind,
                "session_id": trace.session_id,
                "query": trace.query[:4000],
                "plan": _j(trace.data.get("plan")),
                "retrieved": _j(trace.data.get("retrieved")),
                "answer": (trace.data.get("answer") or "")[:20000],
                "verdict": _j(trace.data.get("verdict")),
                "grounding": trace.data.get("grounding"),
                "latency": _j({**trace.stages, "total": trace.total_ms}),
                "usage": _j(trace.usage),
                "error": trace.error,
                "backend": trace.data.get("backend", "antix"),
            },
        )
    except Exception as exc:
        logger.warning("trace persist failed: %s", exc)


def _j(value: Any) -> str | None:
    return None if value is None else json.dumps(value, default=str)
