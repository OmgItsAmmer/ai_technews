"""Article enrichment: summary, key facts, entities, event signature.

Uses the fast model with strict JSON output; falls back to deterministic heuristics
when the model is unavailable or returns garbage, so ingestion never blocks on the LLM.
"""

from __future__ import annotations

import logging
import re
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from antix_ai import prompts
from antix_ai.core.tokens import truncate_tokens
from antix_ai.ingestion.chunker import split_sentences
from antix_ai.ingestion.loader import PostRecord
from antix_ai.providers.base import ChatModel, Message, ProviderError
from antix_ai.providers.structured import complete_structured

logger = logging.getLogger(__name__)

EntityType = Literal["company", "product", "model", "person", "org", "technology", "place", "other"]
ContentType = Literal[
    "news", "announcement", "opinion", "press_release", "tutorial", "research", "rumor", "other"
]


class KeyFact(BaseModel):
    fact: str


class EntityMention(BaseModel):
    name: str
    type: EntityType = "other"
    salience: float = Field(default=0.5, ge=0.0, le=1.0)

    @field_validator("type", mode="before")
    @classmethod
    def _coerce_type(cls, v):
        v = str(v or "other").lower().strip()
        return v if v in EntityType.__args__ else "other"  # type: ignore[attr-defined]

    @field_validator("salience", mode="before")
    @classmethod
    def _clamp(cls, v):
        try:
            return min(1.0, max(0.0, float(v)))
        except (TypeError, ValueError):
            return 0.5


class Enrichment(BaseModel):
    summary_short: str = ""
    key_facts: list[KeyFact] = Field(default_factory=list)
    entities: list[EntityMention] = Field(default_factory=list)
    event_signature: str = ""
    content_type: ContentType = "news"
    importance: float = 0.5
    model: str = "heuristic"

    @field_validator("content_type", mode="before")
    @classmethod
    def _coerce_ct(cls, v):
        v = str(v or "news").lower().strip().replace(" ", "_")
        return v if v in ContentType.__args__ else "other"  # type: ignore[attr-defined]

    @field_validator("importance", mode="before")
    @classmethod
    def _clamp(cls, v):
        try:
            return min(1.0, max(0.0, float(v)))
        except (TypeError, ValueError):
            return 0.5

    @field_validator("key_facts", mode="before")
    @classmethod
    def _facts(cls, v):
        # small models sometimes return plain strings
        return [{"fact": x} if isinstance(x, str) else x for x in (v or [])][:10]

    @field_validator("entities", mode="before")
    @classmethod
    def _ents(cls, v):
        return [{"name": x} if isinstance(x, str) else x for x in (v or [])][:12]


async def enrich(model: ChatModel | None, post: PostRecord, body: str, usage_cb=None) -> Enrichment:
    if model is not None:
        try:
            article = (
                f"Title: {post.title}\nSource: {post.source_name or 'unknown'}\n"
                f"Published: {post.effective_date.date() if post.effective_date else 'unknown'}\n\n"
                f"{truncate_tokens(body, 2500)}"
            )
            result = await complete_structured(
                model,
                [Message("system", prompts.load("enrich")), Message("user", article)],
                Enrichment,
                max_tokens=900,
                usage_cb=usage_cb,
            )
            result.model = model.name
            if result.summary_short and result.key_facts:
                result.key_facts = [f for f in result.key_facts if f.fact.strip()]
                return _merge_heuristic_entities(result, post)
            logger.info("enrichment for post %s incomplete; using heuristics", post.id)
        except ProviderError as exc:
            logger.info("enrichment LLM unavailable for post %s: %s", post.id, exc)
    return heuristic_enrichment(post, body)


# ---------------------------------------------------------------- heuristics

_FACT_SIGNAL = re.compile(
    r"(\$\s?\d|\d+(\.\d+)?\s?(%|percent|million|billion|trillion|bn|m\b|k\b|tokens|parameters|x\b)"
    r"|\b(19|20)\d{2}\b|\bv?\d+\.\d+\b|\b(announced|launched|released|acquired|raised|unveiled|"
    r"introduced|partnered|banned|fined|sued|reported)\b)",
    re.IGNORECASE,
)
_CAPS_SEQ = re.compile(r"\b([A-Z][a-zA-Z0-9]*(?:[-.][A-Za-z0-9]+)*(?:\s+[A-Z][a-zA-Z0-9]*(?:[-.][A-Za-z0-9]+)*){0,3})")
_NOT_ENTITY = frozenset(
    """The A An This That These Those It Its In On At For With From By As But And Or If When While
    After Before During Today Yesterday Tomorrow Monday Tuesday Wednesday Thursday Friday Saturday
    Sunday January February March April May June July August September October November December
    He She They We I You Our Their His Her According However Meanwhile Also Still Now New Read
    More Here There What Why How Who CEO Tell Compare Explain Show Give List Summarize Summarise
    Describe Find Search Is Are Do Does Did Can Could Will Would Should Has Have Was Were Which
    Whose Whom Please Any Some Every Each Both Either Neither Latest Recent Breaking Update
    Updates Based Between Among Using Across Against Within Without About Above Below Under Over
    Since Until Because Though Although""".split()
)


def extract_candidate_entities(text: str, limit: int = 10) -> list[str]:
    counts: dict[str, int] = {}
    for m in _CAPS_SEQ.finditer(text):
        name = m.group(1).strip(" .-")
        words = name.split()
        while words and words[0] in _NOT_ENTITY:
            words = words[1:]
        if not words:
            continue
        name = " ".join(words)
        if len(name) < 2 or name.isdigit():
            continue
        counts[name] = counts.get(name, 0) + 1
    ranked = sorted(counts.items(), key=lambda kv: (-kv[1], -len(kv[0])))
    return [n for n, _ in ranked[:limit]]


def heuristic_enrichment(post: PostRecord, body: str) -> Enrichment:
    sentences = split_sentences(body.replace("\n", " ")) if body else []
    summary = post.summary.strip() or " ".join(sentences[:2])
    summary = " ".join(summary.split()[:60])
    facts = [s for s in sentences if _FACT_SIGNAL.search(s) and 30 <= len(s) <= 400][:6]
    if not facts:
        facts = [s for s in sentences if len(s) >= 30][:3]
    names = extract_candidate_entities(f"{post.title}. {body[:4000]}")
    entities = [EntityMention(name=n, salience=max(0.2, 1.0 - i * 0.1)) for i, n in enumerate(names)]
    result = Enrichment(
        summary_short=summary,
        key_facts=[KeyFact(fact=f) for f in facts],
        entities=entities,
        event_signature=post.title[:120],
        content_type="news",
        importance=0.5,
        model="heuristic",
    )
    return _merge_heuristic_entities(result, post)


def _merge_heuristic_entities(result: Enrichment, post: PostRecord) -> Enrichment:
    """Tags curated by the app are strong entity signals; make sure they're linked."""
    have = {e.name.lower() for e in result.entities}
    for tag in post.tags[:5]:
        if tag.lower() not in have and len(tag) > 1:
            result.entities.append(EntityMention(name=tag, type="technology", salience=0.4))
            have.add(tag.lower())
    return result
