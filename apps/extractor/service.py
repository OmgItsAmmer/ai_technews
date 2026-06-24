import json
import re
from datetime import datetime
from typing import Any

import httpx
from dateutil import parser as date_parser
from django.conf import settings
from openai import OpenAI

from apps.extractor.prompts import EXTRACTION_SYSTEM_PROMPT, EXTRACTION_USER_PROMPT
from apps.extractor.tags import VALID_TAG_SLUGS
from apps.fetcher.scraper import extract_article_text


def _strip_json_fences(raw: str) -> str:
    text = raw.strip()
    fenced = re.match(r"^```(?:json)?\s*(.*?)\s*```$", text, flags=re.DOTALL | re.IGNORECASE)
    if fenced:
        return fenced.group(1).strip()
    return text


def _parse_json_response(raw: str) -> dict[str, Any]:
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return json.loads(_strip_json_fences(raw))


def _parse_published_at(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return date_parser.isoparse(value)
    except (ValueError, TypeError):
        return None


def _normalize_tags(tags: list[str] | None) -> tuple[list[str], list[str]]:
    missing_fields: list[str] = []
    cleaned = [slug for slug in (tags or []) if slug in VALID_TAG_SLUGS]
    if not cleaned:
        missing_fields.append("tags")
    return cleaned, missing_fields


def _build_client() -> OpenAI:
    if settings.OPENAI_BASE_URL:
        return OpenAI(
            base_url=settings.OPENAI_BASE_URL,
            api_key=settings.OPENAI_API_KEY or "not-needed"
        )
    return OpenAI(api_key=settings.OPENAI_API_KEY)


def extract_from_text(text: str) -> dict[str, Any]:
    """Send article text to configured LLM and return structured metadata."""
    client = _build_client()
    response = client.chat.completions.create(
        model=settings.LLM_MODEL,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": EXTRACTION_SYSTEM_PROMPT},
            {"role": "user", "content": EXTRACTION_USER_PROMPT.format(text=text)},
        ],
        temperature=0.2,
    )
    raw_content = response.choices[0].message.content or "{}"
    data = _parse_json_response(raw_content)

    tags, tag_missing = _normalize_tags(data.get("tags"))
    missing_fields = list(data.get("missing_fields") or [])
    for field in tag_missing:
        if field not in missing_fields:
            missing_fields.append(field)

    return {
        "is_valid_news": bool(data.get("is_valid_news")),
        "title": (data.get("title") or "")[:120],
        "author": data.get("author"),
        "published_at": _parse_published_at(data.get("published_at")),
        "summary": data.get("summary") or "",
        "tags": tags,
        "missing_fields": missing_fields,
        "invalid_reason": data.get("invalid_reason"),
    }


def extract_from_url(url: str) -> dict[str, Any]:
    """Fetch a URL, extract article text, and run LLM extraction."""
    text = extract_article_text(url)
    if not text:
        return {
            "is_valid_news": False,
            "title": "",
            "author": None,
            "published_at": None,
            "summary": "",
            "tags": [],
            "missing_fields": ["title", "summary", "tags"],
            "invalid_reason": "Could not extract article text from URL.",
        }
    return extract_from_text(text)


def fetch_url_content(url: str) -> str:
    """Fetch raw page content for debugging or alternate flows."""
    response = httpx.get(url, timeout=30.0, follow_redirects=True)
    response.raise_for_status()
    return response.text
