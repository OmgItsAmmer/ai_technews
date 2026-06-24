from dataclasses import dataclass
from datetime import datetime
from typing import Any

import feedparser
from dateutil import parser as date_parser


@dataclass
class FeedEntry:
    link: str
    title: str
    published_at: datetime | None
    summary: str


def _parse_published_date(entry: dict[str, Any]) -> datetime | None:
    for key in ("published", "updated", "created"):
        raw = entry.get(key)
        if raw:
            try:
                return date_parser.parse(raw)
            except (ValueError, TypeError, OverflowError):
                continue

    parsed = entry.get("published_parsed") or entry.get("updated_parsed")
    if parsed:
        try:
            return datetime(*parsed[:6])
        except (ValueError, TypeError):
            return None

    return None


def _entry_summary(entry: dict[str, Any]) -> str:
    if entry.get("summary"):
        return entry["summary"]
    if entry.get("description"):
        return entry["description"]
    content = entry.get("content")
    if content and isinstance(content, list) and content[0].get("value"):
        return content[0]["value"]
    return ""


def fetch_rss(rss_url: str) -> list[FeedEntry]:
    """Parse an RSS/Atom feed and return lightweight entry objects."""
    parsed = feedparser.parse(rss_url)
    entries: list[FeedEntry] = []

    for entry in parsed.entries:
        link = (entry.get("link") or "").strip()
        title = (entry.get("title") or "").strip()
        if not link or not title:
            continue

        entries.append(
            FeedEntry(
                link=link,
                title=title,
                published_at=_parse_published_date(entry),
                summary=_entry_summary(entry),
            )
        )

    return entries
