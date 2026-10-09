"""Retrieval planner: QueryPlan -> strategy -> ranked, diversified evidence + coverage notes."""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime, timedelta

import numpy as np

from antix_ai.core.cache import stable_hash
from antix_ai.core.tracing import Trace
from antix_ai.providers.base import ProviderError
from antix_ai.query.understanding import QueryPlan
from antix_ai.retrieval.hybrid import Filters, count_in_window, hybrid_search, recent_articles
from antix_ai.retrieval.models import Candidate, RetrievalResult
from antix_ai.retrieval.ranking import blend_rerank, fuse, to_evidence
from antix_ai.retrieval.relevance import filter_relevant
from antix_ai.runtime import Runtime

logger = logging.getLogger(__name__)

NO_RETRIEVAL = {"chit_chat", "out_of_scope"}
ARTICLE_LEVEL = {"latest", "briefing"}
RELAX_STEPS_DAYS = (30, 90, 365)


async def embed_query(rt: Runtime, text: str) -> np.ndarray:
    emb = rt.providers.embedder
    key = stable_hash(emb.name, text)
    cached = await rt.cache.get_json("qemb", key)
    if cached is not None:
        return np.asarray(cached, dtype=np.float32)
    vec = (await emb.embed([text]))[0]
    await rt.cache.set_json("qemb", key, vec.tolist(), rt.settings.cache_embed_ttl)
    return vec


def _filters(plan: QueryPlan, start=None, end=None, require_entity=False) -> Filters:
    w = plan.window()
    return Filters(
        start=start if start is not None else (w.start if w else None),
        end=end if end is not None else (w.end if w else None),
        source_ids=plan.source_ids,
        entity_ids=plan.entity_ids,
        require_entity=require_entity,
    )


async def retrieve(rt: Runtime, plan: QueryPlan, trace: Trace | None = None) -> RetrievalResult:
    if plan.intent in NO_RETRIEVAL:
        return RetrievalResult(strategy="none", articles=[])
    s = rt.settings
    window = plan.window()

    vectors = await asyncio.gather(*(embed_query(rt, q) for q in plan.search_queries))
    entity_scoped = plan.intent in ("entity_overview", "timeline") and bool(plan.entity_ids)
    filters = _filters(plan, require_entity=entity_scoped)

    coverage: dict = {
        "window": window.as_dict() if window else None,
        "sources": plan.source_names,
        "entities": plan.entities,
        "relaxed": None,
    }

    cands = await _gather(rt, plan, vectors, filters)

    # Too little evidence: relax constraints we added ourselves (never explicit user ones)
    if len({c.post_id for c in cands}) < 2:
        if entity_scoped:
            filters = _filters(plan)
            cands = await _gather(rt, plan, vectors, filters)
            coverage["relaxed"] = "entity filter removed"
        if len({c.post_id for c in cands}) < 2 and window and window.source == "default":
            now = datetime.now(UTC)
            for days in RELAX_STEPS_DAYS:
                filters = _filters(plan, start=now - timedelta(days=days), end=window.end,
                                   require_entity=False)
                cands = await _gather(rt, plan, vectors, filters)
                if len({c.post_id for c in cands}) >= 2:
                    coverage["relaxed"] = f"window widened to last {days} days"
                    coverage["window"] = {**(coverage["window"] or {}),
                                          "from": filters.start.isoformat(),
                                          "label": f"last {days} days", "source": "relaxed"}
                    break

    fuse(cands, plan.intent, plan.needs_freshness)
    cands.sort(key=lambda c: c.score, reverse=True)

    # Rerank top-N chunk candidates (article-level paths are already date/importance ranked)
    reranker = rt.providers.reranker
    head = cands[: s.rerank_candidates]
    if head and plan.intent not in ARTICLE_LEVEL and reranker.name != "none":
        try:
            docs = [f"{c.title}\n{c.text[:700]}" for c in head]
            scores = await reranker.rerank(plan.standalone_query, docs)
            blend_rerank(head, scores)
            cands = sorted(head, key=lambda c: c.score, reverse=True) + cands[len(head):]
        except ProviderError as exc:
            logger.info("rerank unavailable, keeping fused order: %s", exc)

    if plan.intent not in ARTICLE_LEVEL or _is_topical(plan):
        cands, dropped = filter_relevant(plan, cands)
        coverage["dropped_irrelevant"] = dropped

    max_articles = s.evidence_articles + (4 if plan.intent in ("briefing", "timeline", "compare") else 0)
    articles = to_evidence(
        cands,
        max_articles=max_articles,
        max_chunks_per_article=s.max_chunks_per_article,
        max_articles_per_story=1 if plan.intent in ARTICLE_LEVEL else s.max_articles_per_story,
    )
    if plan.intent == "timeline":
        articles.sort(key=lambda a: a.published_at or datetime.min.replace(tzinfo=UTC))

    coverage["articles_in_window"] = (
        await count_in_window(rt.db, s.posts_table, _filters(plan)) if window else None
    )
    coverage["matched_articles"] = len(articles)
    coverage["distinct_sources"] = len({a.source_name for a in articles})

    strategy = "article_level" if plan.intent in ARTICLE_LEVEL else "hybrid"
    if trace:
        trace.set(retrieved=[
            {"post_id": a.post_id, "score": a.score, "story": a.story_id,
             "date": a.published_at.isoformat() if a.published_at else None}
            for a in articles
        ])
    return RetrievalResult(strategy=strategy, articles=articles, coverage=coverage)


async def _gather(
    rt: Runtime, plan: QueryPlan, vectors: list[np.ndarray], filters: Filters
) -> list[Candidate]:
    s = rt.settings
    if plan.intent in ARTICLE_LEVEL:
        topical = _is_topical(plan)
        qv = vectors[0] if topical else None
        cands = await recent_articles(rt.db, s.posts_table, filters, qv, limit=60)
        if topical:
            # keep only articles reasonably related to the topic, ranked by similarity
            cands.sort(key=lambda c: c.similarity, reverse=True)
            for rank, c in enumerate(cands, start=1):
                c.vec_rank = rank
            hits = await hybrid_search(
                rt.db, s.posts_table, plan.search_queries[0], vectors[0], filters, k=30
            )
            fts_ranks = {}
            for c in sorted(hits, key=lambda h: h.fts_rank or 10**6):
                if c.fts_rank and c.post_id not in fts_ranks:
                    fts_ranks[c.post_id] = len(fts_ranks) + 1
            for c in cands:
                c.fts_rank = fts_ranks.get(c.post_id)
        return cands

    results = await asyncio.gather(*(
        hybrid_search(rt.db, s.posts_table, q, v, filters, k=s.retrieval_candidates)
        for q, v in zip(plan.search_queries, vectors, strict=True)
    ))
    merged: dict[int, Candidate] = {}
    for hits in results:
        for c in hits:
            prev = merged.get(c.chunk_id)  # type: ignore[arg-type]
            if prev is None:
                merged[c.chunk_id] = c  # type: ignore[index]
            else:  # best rank across sub-queries
                prev.vec_rank = min(filter(None, [prev.vec_rank, c.vec_rank]), default=None)
                prev.fts_rank = min(filter(None, [prev.fts_rank, c.fts_rank]), default=None)
    return list(merged.values())


_GENERIC = {"latest", "news", "recent", "today", "week", "happening", "new", "updates", "update",
            "top", "stories", "headlines", "tech", "technology", "ai", "what", "whats", "briefing",
            "recap", "summary", "summarize", "yesterday", "month", "day", "this", "last", "past"}


def _is_topical(plan: QueryPlan) -> bool:
    words = {w.strip("?.!,'\"").lower() for w in plan.standalone_query.split()}
    from antix_ai.providers.offline import STOPWORDS

    content = {w for w in words if w and w not in STOPWORDS and w not in _GENERIC and len(w) > 2}
    return bool(content) or bool(plan.entity_ids) or bool(plan.entities)
