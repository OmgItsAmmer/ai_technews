"""Retrieval data structures."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class Candidate:
    chunk_id: int | None
    post_id: int
    text: str
    title: str
    source_name: str | None
    source_id: int | None
    url: str | None
    published_at: datetime | None
    story_id: int | None
    summary_short: str
    key_facts: list[dict]
    importance: float
    content_type: str
    story_sources: int = 1
    story_articles: int = 1
    entity_hit: bool = False
    similarity: float = 0.0
    vec_rank: int | None = None
    fts_rank: int | None = None
    score: float = 0.0
    rerank_score: float | None = None


@dataclass
class EvidenceArticle:
    post_id: int
    title: str
    source_name: str | None
    url: str | None
    published_at: datetime | None
    story_id: int | None
    story_sources: int
    summary_short: str
    key_facts: list[dict]
    content_type: str
    passages: list[str] = field(default_factory=list)
    score: float = 0.0
    sid: str = ""  # [S1], [S2] ... assigned by the context builder

    def citation(self) -> dict:
        return {
            "sid": self.sid,
            "post_id": self.post_id,
            "title": self.title,
            "source_name": self.source_name or "Antix News",
            "url": self.url or "",
            "date": self.published_at.date().isoformat() if self.published_at else "",
            "published_at": self.published_at.isoformat() if self.published_at else None,
            "story_id": self.story_id,
        }


@dataclass
class RetrievalResult:
    strategy: str
    articles: list[EvidenceArticle]
    coverage: dict = field(default_factory=dict)
    debug: dict = field(default_factory=dict)
