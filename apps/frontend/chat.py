"""Stub chat service — in-memory per page session (resets on browser refresh)."""

from django.db.models import Q

from apps.posts.models import Post

# (session_token, page_session_id) -> list of message dicts
_chat_store: dict[tuple[str, str], list[dict]] = {}


def _session_key(session_token: str, page_session_id: str) -> tuple[str, str]:
    return session_token, page_session_id


def get_messages(session_token: str, page_session_id: str) -> list[dict]:
    return list(_chat_store.get(_session_key(session_token, page_session_id), []))


def _find_relevant_posts(query: str, limit: int = 3) -> list[Post]:
    words = [w for w in query.lower().split() if len(w) > 2][:6]
    base = Post.objects.filter(status="approved").select_related("source")

    if words:
        q_filter = Q()
        for word in words:
            q_filter |= (
                Q(title__icontains=word)
                | Q(summary__icontains=word)
                | Q(tags__contains=[word])
            )
        matched = list(base.filter(q_filter).order_by("-published_at", "-fetched_at")[:limit])
        if matched:
            return matched

    return list(base.order_by("-published_at", "-fetched_at")[:limit])


def _post_to_citation(ref: int, post: Post) -> dict:
    return {
        "ref": ref,
        "post_id": post.id,
        "title": post.title,
        "source_name": post.source.name if post.source else "Unknown",
        "url": post.original_url or "",
    }


def generate_stub_reply(user_message: str) -> tuple[str, list[dict]]:
    posts = _find_relevant_posts(user_message)
    if not posts:
        return (
            "I couldn't find any approved articles matching that question. Try rephrasing or asking about a specific topic like LLMs, robotics, or cybersecurity.",
            [],
        )

    citations = [_post_to_citation(i + 1, post) for i, post in enumerate(posts)]

    if len(citations) == 1:
        c = citations[0]
        answer = (
            f"Based on recent coverage, {c['title']} [{c['ref']}] "
            f"is a relevant article from {c['source_name']}."
        )
    else:
        parts = [f"{c['title']} [{c['ref']}]" for c in citations[:-1]]
        last = citations[-1]
        answer = (
            f"Based on recent coverage, you may find these articles helpful: "
            f"{', '.join(parts)}, and {last['title']} [{last['ref']}]."
        )

    return answer, citations


def handle_chat_message(session_token: str, page_session_id: str, message: str) -> dict:
    message = (message or "").strip()
    if not message:
        raise ValueError("Message cannot be empty")

    key = _session_key(session_token, page_session_id)
    history = _chat_store.setdefault(key, [])

    history.append({"role": "user", "content": message, "citations": []})

    answer, citations = generate_stub_reply(message)

    history.append({
        "role": "assistant",
        "content": answer,
        "citations": citations,
    })

    return {
        "answer": answer,
        "citations": citations,
        "messages": list(history),
    }
