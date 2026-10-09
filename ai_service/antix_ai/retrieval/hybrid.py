"""Hybrid search (pgvector ANN + Postgres FTS) with metadata filters, in one SQL round-trip.

The posts table is joined on every query, so deleted / un-approved posts can never be
retrieved even if the index has not been reconciled yet.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime

import numpy as np

from antix_ai.core.db import Database
from antix_ai.ingestion.loader import table
from antix_ai.providers.offline import STOPWORDS
from antix_ai.retrieval.models import Candidate

_WORD = re.compile(r"[a-z0-9][a-z0-9+#]*")


@dataclass
class Filters:
    start: datetime | None = None
    end: datetime | None = None
    source_ids: list[int] = field(default_factory=list)
    entity_ids: list[int] = field(default_factory=list)
    require_entity: bool = False
    tags: list[str] = field(default_factory=list)

    def sql(self, alias: str = "c") -> tuple[str, dict]:
        parts, params = ["TRUE"], {}
        if self.start:
            parts.append(f"{alias}.published_at >= %(f_start)s")
            params["f_start"] = self.start
        if self.end:
            parts.append(f"{alias}.published_at < %(f_end)s")
            params["f_end"] = self.end
        if self.source_ids:
            parts.append(f"{alias}.source_id = ANY(%(f_sources)s)")
            params["f_sources"] = self.source_ids
        if self.tags:
            parts.append(f"{alias}.tags && %(f_tags)s")
            params["f_tags"] = self.tags
        if self.require_entity and self.entity_ids:
            parts.append(
                f"EXISTS (SELECT 1 FROM ai.article_entity fe WHERE fe.post_id = {alias}.post_id "
                "AND fe.entity_id = ANY(%(f_entities)s))"
            )
            params["f_entities"] = self.entity_ids
        return " AND ".join(parts), params


def or_tsquery(text: str) -> str | None:
    """OR-of-terms query string for to_tsquery (ranking rewards multi-term matches)."""
    words = [w for w in _WORD.findall(text.lower()) if w not in STOPWORDS and len(w) > 1]
    words = list(dict.fromkeys(words))[:16]
    if not words:
        return None
    # quote each lexeme to keep characters like + and # from breaking the parser
    return " | ".join("'" + w.replace("'", "") + "'" for w in words)


async def hybrid_search(
    db: Database,
    posts_table: str,
    query_text: str,
    query_vec: np.ndarray,
    filters: Filters,
    k: int = 50,
) -> list[Candidate]:
    where, params = filters.sql("c")
    tsq = or_tsquery(query_text)
    params.update({"qv": query_vec, "k": k, "tsq": tsq or "", "eids": filters.entity_ids or []})
    fts_cte = (
        f"""
        fts AS (
            SELECT id, row_number() OVER () AS r FROM (
                SELECT c.id FROM ai.chunk c, to_tsquery('english', %(tsq)s) q
                WHERE c.tsv @@ q AND {where}
                ORDER BY ts_rank_cd(c.tsv, q, 32) DESC LIMIT %(k)s
            ) s
        )"""
        if tsq
        else "fts AS (SELECT NULL::bigint AS id, NULL::bigint AS r WHERE FALSE)"
    )
    sql = f"""
        WITH vec AS (
            SELECT id, row_number() OVER () AS r FROM (
                SELECT c.id FROM ai.chunk c
                WHERE {where}
                ORDER BY c.embedding <=> %(qv)s LIMIT %(k)s
            ) s
        ),
        {fts_cte},
        ids AS (SELECT id FROM vec UNION SELECT id FROM fts)
        SELECT c.id AS chunk_id, c.post_id, c.text, c.published_at, c.source_id,
               1 - (c.embedding <=> %(qv)s) AS similarity,
               a.title, a.url, a.source_name, a.story_id, a.summary_short, a.key_facts,
               a.importance, a.content_type,
               COALESCE(st.source_count, 1) AS story_sources,
               COALESCE(st.article_count, 1) AS story_articles,
               vec.r AS vec_rank, fts.r AS fts_rank,
               EXISTS (SELECT 1 FROM ai.article_entity ae
                       WHERE ae.post_id = c.post_id AND ae.entity_id = ANY(%(eids)s)) AS entity_hit
        FROM ids
        JOIN ai.chunk c ON c.id = ids.id
        JOIN ai.article a ON a.post_id = c.post_id
        JOIN {table(posts_table)} p ON p.id = c.post_id AND p.status = 'approved'
        LEFT JOIN ai.story st ON st.id = a.story_id
        LEFT JOIN vec ON vec.id = c.id
        LEFT JOIN fts ON fts.id = c.id
    """
    rows = await db.fetch(sql, params)
    return [_candidate(r) for r in rows]


def _candidate(r: dict) -> Candidate:
    return Candidate(
        chunk_id=r["chunk_id"],
        post_id=r["post_id"],
        text=r["text"],
        title=r["title"],
        source_name=r["source_name"],
        source_id=r["source_id"],
        url=r["url"],
        published_at=r["published_at"],
        story_id=r["story_id"],
        summary_short=r["summary_short"],
        key_facts=r["key_facts"] or [],
        importance=float(r["importance"]),
        content_type=r["content_type"],
        story_sources=int(r["story_sources"]),
        story_articles=int(r["story_articles"]),
        entity_hit=bool(r["entity_hit"]),
        similarity=float(r["similarity"] or 0.0),
        vec_rank=r["vec_rank"],
        fts_rank=r["fts_rank"],
    )


async def recent_articles(
    db: Database,
    posts_table: str,
    filters: Filters,
    query_vec: np.ndarray | None,
    limit: int = 40,
) -> list[Candidate]:
    """Article-level candidates for latest/briefing: time-filtered, not similarity-limited."""
    where, params = filters.sql("a")
    params.update({"lim": limit, "qv": query_vec, "eids": filters.entity_ids or []})
    sim = "1 - (a.doc_embedding <=> %(qv)s)" if query_vec is not None else "0.0"
    sql = f"""
        SELECT NULL::bigint AS chunk_id, a.post_id, a.summary_short AS text, a.published_at,
               a.source_id, {sim} AS similarity,
               a.title, a.url, a.source_name, a.story_id, a.summary_short, a.key_facts,
               a.importance, a.content_type,
               COALESCE(st.source_count, 1) AS story_sources,
               COALESCE(st.article_count, 1) AS story_articles,
               NULL::bigint AS vec_rank, NULL::bigint AS fts_rank,
               EXISTS (SELECT 1 FROM ai.article_entity ae
                       WHERE ae.post_id = a.post_id AND ae.entity_id = ANY(%(eids)s)) AS entity_hit
        FROM ai.article a
        JOIN {table(posts_table)} p ON p.id = a.post_id AND p.status = 'approved'
        LEFT JOIN ai.story st ON st.id = a.story_id
        WHERE {where}
        ORDER BY a.published_at DESC NULLS LAST
        LIMIT %(lim)s
    """
    rows = await db.fetch(sql, params)
    return [_candidate(r) for r in rows]


async def count_in_window(db: Database, posts_table: str, filters: Filters) -> int:
    where, params = filters.sql("a")
    return int(
        await db.fetchval(
            f"""SELECT count(*) FROM ai.article a
                JOIN {table(posts_table)} p ON p.id = a.post_id AND p.status = 'approved'
                WHERE {where}""",
            params,
        )
        or 0
    )
