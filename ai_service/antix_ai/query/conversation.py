"""Conversation memory: durable (Postgres) + hot (Redis), bounded by a rolling summary."""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel

from antix_ai import prompts
from antix_ai.providers.base import Message, ProviderError
from antix_ai.providers.offline import OfflineChat
from antix_ai.providers.structured import complete_structured
from antix_ai.runtime import Runtime

logger = logging.getLogger(__name__)

HOT_TTL = 6 * 3600
_FOLLOWUP = re.compile(
    r"\b(it|its|it's|they|them|their|this|that|these|those|he|she|his|her|the (company|model|deal|"
    r"product|startup|report|announcement)|what about|how about|and\b|also|more|else|same|why|"
    r"compared)\b",
    re.I,
)


@dataclass
class Turn:
    role: str
    content: str
    citations: list[dict] = field(default_factory=list)


@dataclass
class Session:
    id: str
    turns: list[Turn] = field(default_factory=list)
    summary: str = ""
    focus: dict[str, Any] = field(default_factory=dict)
    turn_count: int = 0

    def to_json(self) -> str:
        return json.dumps(
            {
                "turns": [t.__dict__ for t in self.turns],
                "summary": self.summary,
                "focus": self.focus,
                "turn_count": self.turn_count,
            }
        )

    @classmethod
    def from_json(cls, sid: str, raw: str) -> Session:
        d = json.loads(raw)
        return cls(
            id=sid,
            turns=[Turn(**t) for t in d.get("turns", [])],
            summary=d.get("summary", ""),
            focus=d.get("focus", {}),
            turn_count=d.get("turn_count", 0),
        )


class _Rewrite(BaseModel):
    standalone: str


class _Summary(BaseModel):
    summary: str


def _hot_key(sid: str) -> str:
    return f"antix_ai:session:{sid}"


async def load_session(rt: Runtime, session_id: str) -> Session:
    try:
        raw = await rt.cache.redis.get(_hot_key(session_id))
        if raw:
            return Session.from_json(session_id, raw)
    except Exception as exc:
        logger.warning("session hot load failed: %s", exc)

    conv = await rt.db.fetchrow(
        "SELECT rolling_summary, focus, turn_count FROM ai.conversation WHERE id = %s",
        (session_id,),
    )
    if not conv:
        return Session(id=session_id)
    keep = rt.settings.history_turns * 2
    rows = await rt.db.fetch(
        """
        SELECT role, content, citations FROM (
            SELECT id, role, content, citations FROM ai.message
            WHERE conversation_id = %s ORDER BY id DESC LIMIT %s
        ) t ORDER BY id
        """,
        (session_id, keep),
    )
    return Session(
        id=session_id,
        turns=[Turn(r["role"], r["content"], r["citations"] or []) for r in rows],
        summary=conv["rolling_summary"],
        focus=conv["focus"] or {},
        turn_count=conv["turn_count"],
    )


async def save_turns(
    rt: Runtime,
    session: Session,
    user_text: str,
    answer: str,
    citations: list[dict],
    focus: dict[str, Any],
    trace_id: str | None,
) -> None:
    session.turns += [Turn("user", user_text), Turn("assistant", answer, citations)]
    session.turn_count += 1
    session.focus = focus
    await _compact(rt, session)
    async with rt.db.transaction() as conn:
        await conn.execute(
            """
            INSERT INTO ai.conversation (id, rolling_summary, focus, turn_count)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (id) DO UPDATE SET rolling_summary = EXCLUDED.rolling_summary,
                focus = EXCLUDED.focus, turn_count = EXCLUDED.turn_count, updated_at = now()
            """,
            (session.id, session.summary, json.dumps(focus), session.turn_count),
        )
        await conn.execute(
            """
            INSERT INTO ai.message (conversation_id, role, content, citations, trace_id)
            VALUES (%s, 'user', %s, '[]', %s), (%s, 'assistant', %s, %s, %s)
            """,
            (session.id, user_text, trace_id, session.id, answer, json.dumps(citations), trace_id),
        )
    try:
        await rt.cache.redis.set(_hot_key(session.id), session.to_json(), ex=HOT_TTL)
    except Exception as exc:
        logger.warning("session hot save failed: %s", exc)


async def _compact(rt: Runtime, session: Session) -> None:
    """Fold turns beyond the window into the rolling summary (bounded context forever)."""
    keep = rt.settings.history_turns * 2
    if len(session.turns) <= keep:
        return
    old, session.turns = session.turns[:-keep], session.turns[-keep:]
    transcript = "\n".join(f"{t.role}: {t.content[:600]}" for t in old)
    if session.summary:
        transcript = f"Earlier memory: {session.summary}\n\n{transcript}"
    if not isinstance(rt.providers.fast, OfflineChat):
        try:
            res = await complete_structured(
                rt.providers.fast,
                [Message("system", prompts.load("summarize_history")), Message("user", transcript)],
                _Summary,
                max_tokens=250,
            )
            session.summary = res.summary.strip()[:1200]
            return
        except ProviderError as exc:
            logger.info("history summary LLM unavailable: %s", exc)
    asked = [t.content[:120] for t in old if t.role == "user"]
    session.summary = (session.summary + " | Earlier questions: " + "; ".join(asked))[-1200:]


def needs_rewrite(query: str, session: Session) -> bool:
    if not session.turns:
        return False
    words = query.split()
    return len(words) <= 6 or bool(_FOLLOWUP.search(query))


async def rewrite_standalone(rt: Runtime, query: str, session: Session, usage_cb=None) -> str:
    if not needs_rewrite(query, session):
        return query
    recent = session.turns[-4:]
    convo = "\n".join(f"{t.role}: {t.content[:500]}" for t in recent)
    if session.summary:
        convo = f"(memory) {session.summary}\n{convo}"
    if not isinstance(rt.providers.fast, OfflineChat):
        try:
            res = await complete_structured(
                rt.providers.fast,
                [
                    Message("system", prompts.load("rewrite")),
                    Message("user", f"Conversation:\n{convo}\n\nLatest message: {query}"),
                ],
                _Rewrite,
                max_tokens=150,
                usage_cb=usage_cb,
            )
            if res.standalone.strip():
                return res.standalone.strip()
        except ProviderError as exc:
            logger.info("rewrite LLM unavailable: %s", exc)
    # Deterministic fallback: carry the focus entities / previous question into the query
    focus = ", ".join(session.focus.get("entities", [])[:3])
    last_user = next((t.content for t in reversed(session.turns) if t.role == "user"), "")
    context = focus or last_user[:150]
    return f"{query} (regarding: {context})" if context else query


def history_block(session: Session, max_turns: int = 4) -> str:
    """Compact conversation context for the generator (not the raw transcript)."""
    parts = []
    if session.summary:
        parts.append(f"Earlier in this conversation: {session.summary}")
    for t in session.turns[-max_turns:]:
        content = re.sub(r"\s*\[S\d+\]", "", t.content)[:400]
        parts.append(f"{t.role.upper()}: {content}")
    return "\n".join(parts)
