"""Ingestion orchestration: post -> cleaned chunks + enrichment + embeddings + story."""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime

from antix_ai.ingestion.chunker import chunk_text
from antix_ai.ingestion.cleaner import clean_text
from antix_ai.ingestion.enricher import Enrichment, enrich
from antix_ai.ingestion.entities import link_entities
from antix_ai.ingestion.loader import (
    PostRecord,
    approved_posts_in_window,
    load_post,
    load_posts,
    table,
)
from antix_ai.ingestion.stories import assign_story, prune_empty_stories
from antix_ai.providers.offline import OfflineChat
from antix_ai.runtime import Runtime

logger = logging.getLogger(__name__)

# Bump when chunking/enrichment logic changes so reconcile re-indexes everything.
PIPELINE_VERSION = "2026.10.1"


@dataclass
class IngestResult:
    post_id: int
    status: str  # indexed | unchanged | removed | skipped | failed
    chunks: int = 0
    story_id: int | None = None
    enrich_model: str | None = None
    error: str | None = None


@dataclass
class ReconcileReport:
    checked: int = 0
    indexed: int = 0
    unchanged: int = 0
    removed: int = 0
    failed: int = 0
    errors: list[str] = field(default_factory=list)


def content_hash(post: PostRecord, embed_model: str) -> str:
    payload = json.dumps(
        [
            PIPELINE_VERSION,
            embed_model,
            post.title,
            post.summary,
            post.raw_content,
            sorted(post.tags),
            post.effective_date.isoformat() if post.effective_date else None,
            post.source_id,
            post.url,
        ],
        ensure_ascii=False,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def contextual_prefix(post: PostRecord, enr: Enrichment) -> str:
    """Situates a chunk inside its article; embedded and keyword-indexed with the chunk."""
    date = post.effective_date.strftime("%Y-%m-%d") if post.effective_date else "undated"
    gist = enr.summary_short or post.summary[:200]
    return f"{post.source_name or 'Unknown source'} | {date} | {post.title}. {gist}".strip()


def article_text(post: PostRecord) -> str:
    body = clean_text(post.raw_content)
    summary = clean_text(post.summary)
    if not body:
        return summary or post.title
    # Many feeds put the lede only in the summary; keep it if the body doesn't contain it
    if summary and summary[:80].lower() not in body.lower():
        return f"{summary}\n\n{body}"
    return body


async def remove_article(rt: Runtime, post_id: int) -> bool:
    async with rt.db.transaction() as conn:
        cur = await conn.execute("DELETE FROM ai.article WHERE post_id = %s", (post_id,))
        removed = (cur.rowcount or 0) > 0
        if removed:
            await prune_empty_stories(conn)
    return removed


async def ingest_post(rt: Runtime, post_id: int, *, force: bool = False) -> IngestResult:
    post = await load_post(rt.db, rt.settings, post_id)
    if post is None or post.status != "approved":
        removed = await remove_article(rt, post_id)
        if removed:
            await rt.cache.bump_corpus_version()
        return IngestResult(post_id, "removed" if removed else "skipped")
    try:
        return await _index(rt, post, force=force)
    except Exception as exc:
        logger.exception("ingest failed for post %s", post_id)
        return IngestResult(post_id, "failed", error=str(exc)[:500])


async def _index(rt: Runtime, post: PostRecord, *, force: bool) -> IngestResult:
    s, p = rt.settings, rt.providers
    chash = content_hash(post, p.embedder.name)
    if not force:
        existing = await rt.db.fetchval(
            "SELECT content_hash FROM ai.article WHERE post_id = %s", (post.id,)
        )
        if existing == chash:
            return IngestResult(post.id, "unchanged")

    body = article_text(post)
    chunks = chunk_text(body, s.chunk_target_tokens, s.chunk_overlap_tokens)
    if not chunks:
        return IngestResult(post.id, "skipped", error="empty article")

    use_llm = s.enrich_with_llm and not isinstance(p.fast, OfflineChat)
    enr = await enrich(p.fast if use_llm else None, post, body)

    prefix = contextual_prefix(post, enr)
    facts_text = " ".join(f.fact for f in enr.key_facts[:6])
    doc_text = f"{post.title}\n{enr.summary_short}\n{facts_text}"
    vectors = await p.embedder.embed([doc_text] + [f"{prefix}\n\n{c.text}" for c in chunks])
    doc_vec, chunk_vecs = vectors[0], vectors[1:]

    async with rt.db.transaction() as conn:
        await conn.execute(
            """
            INSERT INTO ai.article (post_id, content_hash, title, url, author, source_id, source_name,
                source_type, published_at, tags, summary_short, key_facts, event_signature,
                content_type, importance, doc_embedding, embed_model, enrich_model, indexed_at)
            VALUES (%(id)s, %(hash)s, %(title)s, %(url)s, %(author)s, %(source_id)s, %(source_name)s,
                %(source_type)s, %(published_at)s, %(tags)s, %(summary)s, %(facts)s, %(sig)s,
                %(ctype)s, %(importance)s, %(doc)s, %(embed_model)s, %(enrich_model)s, now())
            ON CONFLICT (post_id) DO UPDATE SET
                content_hash = EXCLUDED.content_hash, title = EXCLUDED.title, url = EXCLUDED.url,
                author = EXCLUDED.author, source_id = EXCLUDED.source_id,
                source_name = EXCLUDED.source_name, source_type = EXCLUDED.source_type,
                published_at = EXCLUDED.published_at, tags = EXCLUDED.tags,
                summary_short = EXCLUDED.summary_short, key_facts = EXCLUDED.key_facts,
                event_signature = EXCLUDED.event_signature, content_type = EXCLUDED.content_type,
                importance = EXCLUDED.importance, doc_embedding = EXCLUDED.doc_embedding,
                embed_model = EXCLUDED.embed_model, enrich_model = EXCLUDED.enrich_model,
                indexed_at = now()
            """,
            {
                "id": post.id,
                "hash": chash,
                "title": post.title,
                "url": post.url,
                "author": post.author,
                "source_id": post.source_id,
                "source_name": post.source_name,
                "source_type": post.source_type,
                "published_at": post.effective_date,
                "tags": post.tags,
                "summary": enr.summary_short,
                "facts": json.dumps([f.model_dump() for f in enr.key_facts]),
                "sig": enr.event_signature,
                "ctype": enr.content_type,
                "importance": enr.importance,
                "doc": doc_vec,
                "embed_model": p.embedder.name,
                "enrich_model": enr.model,
            },
        )
        await conn.execute("DELETE FROM ai.chunk WHERE post_id = %s", (post.id,))
        async with conn.cursor() as cur:
            await cur.executemany(
                """
                INSERT INTO ai.chunk (post_id, ord, text, contextual_prefix, token_count, embedding,
                                      tsv, published_at, source_id, tags)
                VALUES (%(post_id)s, %(ord)s, %(text)s, %(prefix)s, %(tokens)s, %(emb)s,
                        setweight(to_tsvector('english', %(title)s), 'A') ||
                        setweight(to_tsvector('english', %(tags_text)s || ' ' || %(entities)s), 'B') ||
                        setweight(to_tsvector('english', %(text)s), 'C'),
                        %(published_at)s, %(source_id)s, %(tags)s)
                """,
                [
                    {
                        "post_id": post.id,
                        "ord": c.ord,
                        "text": c.text,
                        "prefix": prefix,
                        "tokens": c.token_count,
                        "emb": vec,
                        "title": post.title,
                        "tags_text": " ".join(post.tags),
                        "entities": " ".join(e.name for e in enr.entities),
                        "published_at": post.effective_date,
                        "source_id": post.source_id,
                        "tags": post.tags,
                    }
                    for c, vec in zip(chunks, chunk_vecs, strict=True)
                ],
            )
        entity_ids = await link_entities(conn, post.id, enr.entities, post.effective_date)
        existing_story = await (
            await conn.execute("SELECT story_id FROM ai.article WHERE post_id = %s", (post.id,))
        ).fetchone()
        story_id = existing_story["story_id"] if existing_story else None
        if story_id is None:
            story_id = await assign_story(
                conn,
                post_id=post.id,
                headline=post.title,
                signature=enr.event_signature,
                published_at=post.effective_date,
                doc_embedding=doc_vec,
                entity_ids=entity_ids,
                window_hours=s.story_window_hours,
                threshold=s.story_similarity,
                entity_floor=s.story_entity_floor,
            )

    await rt.cache.bump_corpus_version()
    logger.info(
        "indexed post",
        extra={"data": {"post_id": post.id, "chunks": len(chunks), "story_id": story_id,
                        "enrich_model": enr.model}},
    )
    return IngestResult(post.id, "indexed", len(chunks), story_id, enr.model)


async def ingest_many(rt: Runtime, post_ids: list[int], *, force: bool = False) -> list[IngestResult]:
    results = []
    posts = {p.id: p for p in await load_posts(rt.db, rt.settings, post_ids)}
    for pid in post_ids:
        post = posts.get(pid)
        if post is None or post.status != "approved":
            results.append(await ingest_post(rt, pid))
            continue
        try:
            results.append(await _index(rt, post, force=force))
        except Exception as exc:
            logger.exception("ingest failed for post %s", pid)
            results.append(IngestResult(pid, "failed", error=str(exc)[:500]))
    return results


async def reconcile(rt: Runtime, days: int | None = None, *, force: bool = False) -> ReconcileReport:
    """Make the index match the app: index new/changed approved posts, drop removed ones."""
    days = days or rt.settings.backfill_days
    report = ReconcileReport()
    posts = await approved_posts_in_window(rt.db, rt.settings, days)
    hashes = {
        r["post_id"]: r["content_hash"]
        for r in await rt.db.fetch("SELECT post_id, content_hash FROM ai.article")
    }
    for post in posts:
        report.checked += 1
        if not force and hashes.get(post.id) == content_hash(post, rt.providers.embedder.name):
            report.unchanged += 1
            continue
        try:
            res = await _index(rt, post, force=True)
        except Exception as exc:
            logger.exception("reconcile: post %s failed", post.id)
            res = IngestResult(post.id, "failed", error=str(exc)[:300])
        if res.status == "indexed":
            report.indexed += 1
        elif res.status == "failed":
            report.failed += 1
            report.errors.append(f"{post.id}: {res.error}")

    # Remove articles whose post was deleted or un-approved
    stale = await rt.db.fetch(
        f"""
        SELECT a.post_id FROM ai.article a
        LEFT JOIN {table(rt.settings.posts_table)} p ON p.id = a.post_id
        WHERE p.id IS NULL OR p.status <> 'approved'
        """
    )
    for row in stale:
        if await remove_article(rt, row["post_id"]):
            report.removed += 1
    if report.removed:
        await rt.cache.bump_corpus_version()
    return report


def now_utc() -> datetime:
    from datetime import UTC

    return datetime.now(UTC)
