"""News-intelligence features that need no LLM generation: stories, related, trends, briefing data."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from antix_ai.ingestion.loader import table
from antix_ai.query.timeparse import default_window, parse_time_range
from antix_ai.runtime import Runtime


def _article_row(r: dict) -> dict:
    return {
        "post_id": r["post_id"],
        "title": r["title"],
        "source_name": r["source_name"],
        "url": r["url"],
        "published_at": r["published_at"].isoformat() if r["published_at"] else None,
        "summary": r["summary_short"],
        "tags": r["tags"],
        "importance": r["importance"],
        "story_id": r["story_id"],
    }


async def briefing(rt: Runtime, range_text: str = "today", tz: str | None = None, limit: int = 10) -> dict:
    """Top stories in a window: one lead article per story, ranked by importance x corroboration."""
    now = datetime.now(UTC)
    window = parse_time_range(range_text, now, tz or rt.settings.default_timezone) or default_window(
        now, 1, "last day"
    )
    rows = await rt.db.fetch(
        f"""
        SELECT DISTINCT ON (COALESCE(a.story_id, -a.post_id))
               a.*, st.source_count, st.article_count,
               (a.importance * (1 + 0.15 * LEAST(COALESCE(st.source_count, 1) - 1, 4))) AS rank_score
        FROM ai.article a
        JOIN {table(rt.settings.posts_table)} p ON p.id = a.post_id AND p.status = 'approved'
        LEFT JOIN ai.story st ON st.id = a.story_id
        WHERE a.published_at >= %(s)s AND a.published_at < %(e)s
        ORDER BY COALESCE(a.story_id, -a.post_id), a.importance DESC, a.published_at ASC
        """,
        {"s": window.start, "e": window.end},
    )
    rows.sort(key=lambda r: r["rank_score"], reverse=True)
    stories = []
    for r in rows[:limit]:
        item = _article_row(r)
        item.update(sources=int(r["source_count"] or 1), articles=int(r["article_count"] or 1),
                    key_facts=[f["fact"] for f in (r["key_facts"] or [])][:3])
        stories.append(item)
    return {"window": window.as_dict(), "total_stories": len(rows), "stories": stories}


async def related(rt: Runtime, post_id: int, limit: int = 6) -> list[dict]:
    rows = await rt.db.fetch(
        f"""
        WITH me AS (SELECT doc_embedding, story_id FROM ai.article WHERE post_id = %(id)s)
        SELECT a.*, 1 - (a.doc_embedding <=> me.doc_embedding) AS sim
        FROM ai.article a CROSS JOIN me
        WHERE a.post_id <> %(id)s
          AND EXISTS (SELECT 1 FROM {table(rt.settings.posts_table)} p
                      WHERE p.id = a.post_id AND p.status = 'approved')
        ORDER BY a.doc_embedding <=> me.doc_embedding
        LIMIT %(lim)s
        """,
        {"id": post_id, "lim": limit},
    )
    return [{**_article_row(r), "similarity": round(float(r["sim"]), 3)} for r in rows]


async def story(rt: Runtime, story_id: int) -> dict | None:
    st = await rt.db.fetchrow(
        "SELECT id, headline, first_seen, last_updated, article_count, source_count FROM ai.story WHERE id = %s",
        (story_id,),
    )
    if not st:
        return None
    rows = await rt.db.fetch(
        f"""
        SELECT a.* FROM ai.article a
        JOIN {table(rt.settings.posts_table)} p ON p.id = a.post_id AND p.status = 'approved'
        WHERE a.story_id = %s ORDER BY a.published_at
        """,
        (story_id,),
    )
    return {
        "id": st["id"],
        "headline": st["headline"],
        "first_seen": st["first_seen"].isoformat(),
        "last_updated": st["last_updated"].isoformat(),
        "sources": st["source_count"],
        "timeline": [_article_row(r) for r in rows],
    }


async def trending(rt: Runtime, days: int = 7, limit: int = 15) -> list[dict]:
    """Entities whose mention rate in the last ``days`` rose most versus the previous period."""
    now = datetime.now(UTC)
    rows = await rt.db.fetch(
        """
        SELECT e.id, e.name, e.type,
               count(*) FILTER (WHERE a.published_at >= %(mid)s) AS recent,
               count(*) FILTER (WHERE a.published_at <  %(mid)s) AS previous
        FROM ai.article_entity ae
        JOIN ai.entity e ON e.id = ae.entity_id
        JOIN ai.article a ON a.post_id = ae.post_id
        WHERE a.published_at >= %(lo)s AND ae.salience >= 0.4
        GROUP BY e.id, e.name, e.type
        HAVING count(*) FILTER (WHERE a.published_at >= %(mid)s) >= 2
        """,
        {"mid": now - timedelta(days=days), "lo": now - timedelta(days=2 * days)},
    )
    out: list[dict[str, Any]] = []
    for r in rows:
        velocity = (r["recent"] + 1) / (r["previous"] + 1)
        out.append({"entity_id": r["id"], "name": r["name"], "type": r["type"],
                    "mentions": r["recent"], "previous": r["previous"],
                    "velocity": round(velocity, 2)})
    out.sort(key=lambda x: (x["velocity"], x["mentions"]), reverse=True)
    return out[:limit]


async def stats(rt: Runtime) -> dict:
    row = await rt.db.fetchrow(
        f"""
        SELECT (SELECT count(*) FROM ai.article) AS articles,
               (SELECT count(*) FROM ai.chunk) AS chunks,
               (SELECT count(*) FROM ai.story) AS stories,
               (SELECT count(*) FROM ai.entity) AS entities,
               (SELECT max(indexed_at) FROM ai.article) AS last_indexed,
               (SELECT count(*) FROM {table(rt.settings.posts_table)} WHERE status='approved') AS approved_posts
        """
    )
    row["last_indexed"] = row["last_indexed"].isoformat() if row["last_indexed"] else None
    row["unindexed"] = max(0, row["approved_posts"] - row["articles"])
    row["embed_model"] = rt.providers.embedder.name
    return row
