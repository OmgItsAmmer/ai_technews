"""Score fusion, rerank blending, and diversification."""

from __future__ import annotations

import math
from collections import defaultdict
from datetime import UTC, datetime

from antix_ai.retrieval.models import Candidate, EvidenceArticle

RRF_K = 60

# Recency half-life (days) per intent; None = recency not used for ranking
HALF_LIFE = {
    "latest": 2.0, "briefing": 1.0, "entity_overview": 10.0, "analysis": 20.0,
    "fact_lookup": 45.0, "compare": 30.0, "timeline": None, "explain_concept": None,
}


def fuse(cands: list[Candidate], intent: str, needs_freshness: bool, now: datetime | None = None) -> None:
    """Reciprocal rank fusion + multiplicative priors (recency, entity, importance, corroboration)."""
    now = now or datetime.now(UTC)
    half_life = HALF_LIFE.get(intent, 30.0)
    if needs_freshness and half_life is None:
        half_life = 14.0
    for c in cands:
        s = 0.0
        if c.vec_rank:
            s += 1.0 / (RRF_K + c.vec_rank)
        if c.fts_rank:
            s += 1.0 / (RRF_K + c.fts_rank)
        if not c.vec_rank and not c.fts_rank:  # article-level candidates
            s = 1.0 / RRF_K * (0.5 + c.similarity)
        if half_life and c.published_at:
            age = max(0.0, (now - c.published_at).total_seconds() / 86400)
            s *= 0.55 + 0.45 * math.exp(-math.log(2) * age / half_life)
        if c.entity_hit:
            s *= 1.35
        s *= 0.85 + 0.3 * c.importance
        s *= 1.0 + 0.05 * min(c.story_sources - 1, 4)  # multi-source corroboration
        if c.content_type in ("rumor", "press_release"):
            s *= 0.9
        c.score = s


def blend_rerank(cands: list[Candidate], scores: list[float] | None, weight: float = 0.7) -> None:
    if not scores:
        return
    max_fused = max((c.score for c in cands), default=1.0) or 1.0
    lo, hi = min(scores), max(scores)
    span = (hi - lo) or 1.0
    for c, r in zip(cands, scores, strict=True):
        c.rerank_score = (r - lo) / span
        c.score = weight * c.rerank_score + (1 - weight) * (c.score / max_fused)


def to_evidence(
    cands: list[Candidate],
    *,
    max_articles: int,
    max_chunks_per_article: int,
    max_articles_per_story: int,
) -> list[EvidenceArticle]:
    """Group chunks by article, cap per story (dedup the same event), keep best articles."""
    by_post: dict[int, list[Candidate]] = defaultdict(list)
    for c in sorted(cands, key=lambda c: c.score, reverse=True):
        by_post[c.post_id].append(c)

    per_story: dict[int, int] = defaultdict(int)
    out: list[EvidenceArticle] = []
    for _post_id, chunks in sorted(by_post.items(), key=lambda kv: kv[1][0].score, reverse=True):
        head = chunks[0]
        if head.story_id is not None:
            if per_story[head.story_id] >= max_articles_per_story:
                continue
            per_story[head.story_id] += 1
        passages = []
        for ch in chunks[:max_chunks_per_article]:
            if ch.chunk_id is not None and ch.text and ch.text not in passages:
                passages.append(ch.text)
        out.append(
            EvidenceArticle(
                post_id=head.post_id,
                title=head.title,
                source_name=head.source_name,
                url=head.url,
                published_at=head.published_at,
                story_id=head.story_id,
                story_sources=head.story_sources,
                summary_short=head.summary_short,
                key_facts=head.key_facts,
                content_type=head.content_type,
                passages=passages,
                score=round(head.score, 6),
            )
        )
        if len(out) >= max_articles:
            break
    return out
