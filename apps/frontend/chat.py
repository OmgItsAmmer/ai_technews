import hashlib
import logging
import re
import threading
import time
from typing import Any

from django.conf import settings

from apps.frontend.scrutinize import ScrutinizeClient
from apps.posts.models import Post

logger = logging.getLogger(__name__)

# In-memory store for chat session history (legacy Scrutinize backend only).
# The Antix AI service persists conversations itself.
_CHAT_SESSIONS: dict[tuple[str, str], list[dict[str, Any]]] = {}

_SID_RE = re.compile(r"\[S(\d+)\]")


def ai_session_id(session_token: str, page_session_id: str) -> str:
    raw = f"{session_token}:{page_session_id}"
    return raw if len(raw) <= 100 else hashlib.sha256(raw.encode()).hexdigest()


def _to_ui_answer(text: str) -> str:
    """The service cites as [S2]; the UI's citation cards are labelled [#2]."""
    return _SID_RE.sub(lambda m: f"[#{m.group(1)}]", text)


def _to_ui_citations(citations: list[dict]) -> list[dict]:
    return [
        {
            "index": int(str(c.get("sid", "S0"))[1:] or 0),
            "post_id": c.get("post_id"),
            "title": c.get("title", ""),
            "source_name": c.get("source_name", "Antix News"),
            "url": c.get("url", ""),
            "date": c.get("date", ""),
            "snippet": "",
        }
        for c in citations
    ]


def get_chat_history(session_token: str, page_session_id: str) -> list[dict[str, Any]]:
    if settings.AI_BACKEND == "antix":
        from apps.ai.client import AIClient, AIUnavailable

        try:
            msgs = AIClient().conversation(ai_session_id(session_token, page_session_id))
        except AIUnavailable:
            return []
        return [
            {
                "role": m["role"],
                "content": _to_ui_answer(m["content"]) if m["role"] == "assistant" else m["content"],
                "citations": _to_ui_citations(m.get("citations") or []),
                "trace_id": m.get("trace_id"),
            }
            for m in msgs
        ]
    return _CHAT_SESSIONS.get((session_token, page_session_id), [])


def handle_chat_message(session_token: str, page_session_id: str, message: str) -> dict[str, Any]:
    backend = settings.AI_BACKEND
    if backend == "antix":
        try:
            return _handle_antix(session_token, page_session_id, message)
        except Exception:
            logger.exception("Antix AI service failed")
            if not settings.AI_FALLBACK_TO_SCRUTINIZE:
                return _error_reply(session_token, page_session_id, message)
            logger.warning("falling back to Scrutinize for this request")
    started = time.perf_counter()
    result = _handle_scrutinize(session_token, page_session_id, message)
    if backend == "shadow":
        elapsed = (time.perf_counter() - started) * 1000
        threading.Thread(
            target=_shadow_compare, args=(message, result, elapsed, session_token, page_session_id), daemon=True
        ).start()
    return result


def _error_reply(session_token: str, page_session_id: str, message: str) -> dict[str, Any]:
    answer = "I couldn't reach the AI engine right now. Please try again in a moment."
    return {"answer": answer, "citations": [], "messages": get_chat_history(session_token, page_session_id)
            + [{"role": "user", "content": message}, {"role": "assistant", "content": answer, "citations": []}]}


# ------------------------------------------------------------------ Antix


def _handle_antix(session_token: str, page_session_id: str, message: str) -> dict[str, Any]:
    from apps.ai.client import AIClient

    res = AIClient().ask(message, session_id=ai_session_id(session_token, page_session_id))
    return {
        "answer": _to_ui_answer(res["answer"]),
        "citations": _to_ui_citations(res["citations"]),
        "trace_id": res.get("trace_id"),
        "grounding": res.get("grounding"),
        "messages": get_chat_history(session_token, page_session_id),
    }


def _shadow_compare(message, legacy, elapsed_ms, session_token, page_session_id) -> None:
    """Run the new service on the same question (isolated session) and log the legacy answer for comparison."""
    from apps.ai.client import AIClient, AIUnavailable

    try:
        client = AIClient()
        client.ask(message, session_id=f"shadow:{ai_session_id(session_token, page_session_id)}")
        client.shadow(
            message,
            legacy.get("answer", ""),
            [c["post_id"] for c in legacy.get("citations", []) if c.get("post_id")],
            elapsed_ms,
        )
    except AIUnavailable:
        logger.info("shadow comparison skipped: AI service unavailable")
    except Exception:
        logger.exception("shadow comparison failed")


# -------------------------------------------------------------- Scrutinize


def _handle_scrutinize(session_token: str, page_session_id: str, message: str) -> dict[str, Any]:
    """Handle incoming Ask AI query, invoke Scrutinize RAG search, and format database citations."""
    key = (session_token, page_session_id)
    history = _CHAT_SESSIONS.setdefault(key, [])

    # Append user query
    history.append({"role": "user", "content": message})

    # Prepare conversation history format for Scrutinize API (up to last 10 messages)
    conv_messages = [
        {"role": msg["role"], "content": msg["content"]}
        for msg in history[:-1]
        if msg["role"] in ("user", "assistant")
    ][-10:]

    client = ScrutinizeClient()
    conv_payload = {"messages": conv_messages} if conv_messages else None
    res = client.search(query=message, conversation=conv_payload)

    if not res:
        answer = "I apologize, but I couldn't reach the AI intelligence engine right now. Please check back shortly."
        raw_sources = []
    else:
        answer = res.get("answer", "No response generated.")
        raw_sources = res.get("sources", [])

    citations = []
    seen_ids = set()
    for idx, src in enumerate(raw_sources, start=1):
        filename = src.get("filename", "")
        file_id = src.get("file_id")
        content_snippet = src.get("content", "")[:160]

        post = None
        # Match post_{id}.txt pattern
        match = re.match(r"^post_(\d+)\.txt$", filename)
        if match:
            post_id = int(match.group(1))
            if post_id not in seen_ids:
                seen_ids.add(post_id)
                post = Post.objects.filter(id=post_id).select_related("source").first()
        elif file_id:
            post = Post.objects.filter(scrutinize_file_id=file_id).select_related("source").first()
            if post and post.id not in seen_ids:
                seen_ids.add(post.id)
            else:
                post = None

        if post:
            citations.append({
                "index": idx,
                "post_id": post.id,
                "title": post.title,
                "source_name": post.source.name if post.source else "Antix News",
                "url": post.original_url or "",
                "date": post.published_at.strftime("%b %d, %Y") if post.published_at else "",
                "snippet": content_snippet,
            })
        else:
            citations.append({
                "index": idx,
                "post_id": None,
                "title": filename or f"Document #{idx}",
                "source_name": "Knowledge Base",
                "url": "",
                "date": "",
                "snippet": content_snippet,
            })

    reply_msg = {
        "role": "assistant",
        "content": answer,
        "citations": citations,
    }
    history.append(reply_msg)

    return {
        "answer": answer,
        "citations": citations,
        "messages": history,
    }
