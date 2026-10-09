"""Relevance gate: nearest-neighbour search always returns *something*; this decides if it's evidence.

Two checks, applied before articles reach the model:

1. Entity gate (hard). If the question names entities (companies, products, people), a candidate
   article must actually mention at least one of them (index link or text). Asking about an entity that
   is not in our news yields no evidence, so the assistant says so instead of improvising from
   loosely-related articles.
2. Term gate (soft). An article sharing no content term with the question AND with weak semantic
   similarity is dropped.
"""

from __future__ import annotations

import re

from antix_ai.providers.offline import STOPWORDS, tokenize
from antix_ai.query.understanding import QueryPlan
from antix_ai.retrieval.models import Candidate

GENERIC_NAME_TOKENS = frozenset(
    "inc corp ltd llc labs lab systems technologies technology dynamics group holdings company "
    "ai the new model models news latest update updates tech".split()
)
# Terms that appear in almost every question and carry no topical signal
GENERIC_TERMS = frozenset(
    "say said detail details article articles report reports recent happen happened happening "
    "announce announced announcement release released launch launched according difference "
    "compare comparison based change changed mean means "
    # time words are handled by the time filter, never by topical matching
    "today yesterday tonight tomorrow week weeks weekend month months year years day days morning "
    "monday tuesday wednesday thursday friday saturday sunday "
    # domain-wide words that appear in nearly every article on this site
    "artificial intelligence tech technology technologies".split()
)
SEMANTIC_FLOOR = 0.42  # cosine; unrelated text sits well below this with real embedding models


def name_tokens(name: str) -> list[str]:
    toks = [t.rstrip(".-") for t in re.findall(r"[a-z0-9][a-z0-9.+#-]*", name.lower())]
    return [t for t in toks if len(t) >= 3 and t not in STOPWORDS and t not in GENERIC_NAME_TOKENS]


def _haystack(c: Candidate) -> str:
    return f"{c.title} {c.summary_short} {c.text}".lower()


def _mentions(hay: str, tokens: list[str]) -> bool:
    return any(re.search(rf"(?<![a-z0-9]){re.escape(t)}", hay) for t in tokens)


def filter_relevant(plan: QueryPlan, cands: list[Candidate]) -> tuple[list[Candidate], int]:
    """Return (kept candidates, number of articles dropped)."""
    if not cands:
        return cands, 0

    entity_token_sets = [t for t in (name_tokens(e) for e in plan.entities) if t]
    terms = {t for t in tokenize(plan.standalone_query) if t not in GENERIC_TERMS and len(t) > 2}
    # entity tokens are covered by the entity gate; the term gate checks the rest
    entity_flat = {t for ts in entity_token_sets for t in ts}
    topical_terms = {t for t in terms if t not in entity_flat}

    by_post: dict[int, list[Candidate]] = {}
    for c in cands:
        by_post.setdefault(c.post_id, []).append(c)

    keep_posts: set[int] = set()
    for post_id, chunks in by_post.items():
        hay = " ".join(_haystack(c) for c in chunks)
        stems = set(tokenize(hay))
        if entity_token_sets:
            has_entity = any(c.entity_hit for c in chunks) or any(
                _mentions(hay, ts) for ts in entity_token_sets
            )
            if not has_entity:
                continue
        elif topical_terms:
            overlap = bool(topical_terms & stems)
            best_sim = max(c.similarity for c in chunks)
            strong_rank = any((c.rerank_score or 0) >= 0.6 for c in chunks)
            if not overlap and best_sim < SEMANTIC_FLOOR and not strong_rank:
                continue
        keep_posts.add(post_id)

    kept = [c for c in cands if c.post_id in keep_posts]
    return kept, len(by_post) - len(keep_posts)
