import logging
import re
from typing import Any

from apps.frontend.scrutinize import ScrutinizeClient
from apps.posts.models import Post

logger = logging.getLogger(__name__)

# In-memory store for chat session history keyed by (session_token, page_session_id)
_CHAT_SESSIONS: dict[tuple[str, str], list[dict[str, Any]]] = {}


def get_chat_history(session_token: str, page_session_id: str) -> list[dict[str, Any]]:
    return _CHAT_SESSIONS.get((session_token, page_session_id), [])


def handle_chat_message(session_token: str, page_session_id: str, message: str) -> dict[str, Any]:
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
                "source_name": post.source.name if post.source else "Rapid News",
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
