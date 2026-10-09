"""Read posts from the Django-owned tables (read-only)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime

from antix_ai.config import Settings
from antix_ai.core.db import Database

_IDENT = re.compile(r"^[a-z_][a-z0-9_]*(\.[a-z_][a-z0-9_]*)?$")


def table(name: str) -> str:
    """Validate a configured table name before interpolating it into SQL."""
    if not _IDENT.match(name):
        raise ValueError(f"invalid table identifier: {name!r}")
    return name


@dataclass
class PostRecord:
    id: int
    title: str
    url: str | None
    author: str | None
    published_at: datetime | None
    fetched_at: datetime | None
    raw_content: str
    summary: str
    tags: list[str]
    status: str
    source_id: int | None
    source_name: str | None
    source_type: str | None

    @property
    def effective_date(self) -> datetime | None:
        return self.published_at or self.fetched_at


def _select(s: Settings) -> str:
    return f"""
        SELECT p.id, p.title, p.original_url AS url, p.author, p.published_at, p.fetched_at,
               p.raw_content, p.summary, p.tags, p.status, p.source_id,
               s.name AS source_name, s.source_type
        FROM {table(s.posts_table)} p
        LEFT JOIN {table(s.sources_table)} s ON s.id = p.source_id
    """


def _to_record(row: dict) -> PostRecord:
    tags = row.get("tags") or []
    if not isinstance(tags, list):
        tags = [str(tags)]
    return PostRecord(
        id=row["id"],
        title=row["title"] or "",
        url=row["url"],
        author=row["author"],
        published_at=row["published_at"],
        fetched_at=row["fetched_at"],
        raw_content=row["raw_content"] or "",
        summary=row["summary"] or "",
        tags=[str(t) for t in tags if t],
        status=row["status"],
        source_id=row["source_id"],
        source_name=row["source_name"],
        source_type=row["source_type"],
    )


async def load_posts(db: Database, s: Settings, ids: list[int]) -> list[PostRecord]:
    rows = await db.fetch(_select(s) + " WHERE p.id = ANY(%s)", (ids,))
    return [_to_record(r) for r in rows]


async def load_post(db: Database, s: Settings, post_id: int) -> PostRecord | None:
    posts = await load_posts(db, s, [post_id])
    return posts[0] if posts else None


async def approved_posts_in_window(db: Database, s: Settings, days: int) -> list[PostRecord]:
    rows = await db.fetch(
        _select(s)
        + """ WHERE p.status = 'approved'
              AND COALESCE(p.published_at, p.fetched_at) >= now() - make_interval(days => %s)
              ORDER BY COALESCE(p.published_at, p.fetched_at) DESC""",
        (days,),
    )
    return [_to_record(r) for r in rows]
