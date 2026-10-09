"""Story clustering: group articles from different outlets about the same event."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

import numpy as np
from psycopg import AsyncConnection

logger = logging.getLogger(__name__)


async def assign_story(
    conn: AsyncConnection,
    *,
    post_id: int,
    headline: str,
    signature: str,
    published_at: datetime | None,
    doc_embedding: np.ndarray,
    entity_ids: list[int],
    window_hours: int,
    threshold: float,
    entity_floor: float = 0.55,
) -> int:
    """Attach the article to the best matching recent story, or start a new one.

    Match tiers (cosine to the story centroid):
      sim >= threshold
      sim >= threshold - 0.10 and >= 2 shared entities
      sim >= entity_floor     and >= 3 shared entities
    """
    ts = published_at or datetime.now().astimezone()
    cur = await conn.execute(
        """
        SELECT id, 1 - (centroid <=> %(e)s) AS sim,
               cardinality(ARRAY(SELECT unnest(entity_ids) INTERSECT SELECT unnest(%(ents)s::bigint[]))) AS shared
        FROM ai.story
        WHERE last_updated >= %(lo)s AND first_seen <= %(hi)s AND centroid IS NOT NULL
        ORDER BY centroid <=> %(e)s
        LIMIT 5
        """,
        {
            "e": doc_embedding,
            "ents": entity_ids[:6],
            "lo": ts - timedelta(hours=window_hours),
            "hi": ts + timedelta(hours=window_hours),
        },
    )
    best = None
    for row in await cur.fetchall():
        sim, shared = float(row["sim"]), int(row["shared"])
        if (
            sim >= threshold
            or (sim >= threshold - 0.10 and shared >= 2)
            or (sim >= entity_floor and shared >= 3)
        ):
            best = row
            break

    if best is None:
        cur = await conn.execute(
            """
            INSERT INTO ai.story (headline, signature, first_seen, last_updated, article_count,
                                  source_count, entity_ids, centroid)
            VALUES (%s, %s, %s, %s, 0, 0, %s, %s) RETURNING id
            """,
            (headline, signature, ts, ts, entity_ids[:6], doc_embedding),
        )
        story_id = (await cur.fetchone())["id"]
    else:
        story_id = best["id"]

    await conn.execute("UPDATE ai.article SET story_id = %s WHERE post_id = %s", (story_id, post_id))
    await refresh_story(conn, story_id)
    return story_id


async def refresh_story(conn: AsyncConnection, story_id: int) -> None:
    """Recompute counts, centroid, time span, entities and headline from member articles."""
    await conn.execute(
        """
        WITH members AS (
            SELECT post_id, source_id, published_at, title, importance, doc_embedding
            FROM ai.article WHERE story_id = %(id)s
        ), ents AS (
            SELECT ae.entity_id FROM ai.article_entity ae
            JOIN members m ON m.post_id = ae.post_id
            GROUP BY ae.entity_id ORDER BY sum(ae.salience) DESC LIMIT 8
        )
        UPDATE ai.story s SET
            article_count = (SELECT count(*) FROM members),
            source_count  = (SELECT count(DISTINCT source_id) FROM members),
            first_seen    = COALESCE((SELECT min(published_at) FROM members), s.first_seen),
            last_updated  = COALESCE((SELECT max(published_at) FROM members), s.last_updated),
            centroid      = COALESCE((SELECT l2_normalize(avg(doc_embedding)) FROM members), s.centroid),
            entity_ids    = COALESCE((SELECT array_agg(entity_id) FROM ents), s.entity_ids),
            headline      = COALESCE((SELECT title FROM members
                                      ORDER BY importance DESC, published_at ASC LIMIT 1), s.headline)
        WHERE s.id = %(id)s
        """,
        {"id": story_id},
    )


async def prune_empty_stories(conn: AsyncConnection) -> int:
    cur = await conn.execute(
        "DELETE FROM ai.story s WHERE NOT EXISTS "
        "(SELECT 1 FROM ai.article a WHERE a.story_id = s.id)"
    )
    return cur.rowcount or 0
