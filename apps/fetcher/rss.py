from dataclasses import dataclass
from datetime import datetime
from typing import Any

import feedparser
from bs4 import BeautifulSoup
from dateutil import parser as date_parser


@dataclass
class FeedEntry:
    link: str
    title: str
    published_at: datetime | None
    summary: str
    author: str | None = None


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


def _plain_text(value: str) -> str:
    """Strip HTML markup from RSS snippet fields."""
    text = BeautifulSoup(value, "html.parser").get_text(separator=" ", strip=True)
    return " ".join(text.split())


def _entry_summary(entry: dict[str, Any]) -> str:
    raw = ""
    if entry.get("summary"):
        raw = entry["summary"]
    elif entry.get("description"):
        raw = entry["description"]
    else:
        content = entry.get("content")
        if content and isinstance(content, list) and content[0].get("value"):
            raw = content[0]["value"]
    if not raw:
        return ""
    return _plain_text(raw)


def _entry_author(entry: dict[str, Any]) -> str | None:
    author = (entry.get("author") or "").strip()
    if author:
        return author
    authors = entry.get("authors")
    if authors and isinstance(authors, list):
        name = (authors[0].get("name") or "").strip()
        if name:
            return name
    detail = entry.get("author_detail") or {}
    name = (detail.get("name") or "").strip()
    return name or None


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
                author=_entry_author(entry),
            )
        )

    return entries
