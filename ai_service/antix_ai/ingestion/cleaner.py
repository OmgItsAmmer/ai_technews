"""Normalize scraped article text."""

from __future__ import annotations

import html
import re
import unicodedata

_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"[ \t ]+")
_BOILERPLATE = re.compile(
    r"^(advertisement|sponsored|subscribe( now)?|sign up.*newsletter.*|read more:?.*|"
    r"share (this|on).*|follow us.*|click here.*|accept (all )?cookies.*|"
    r"related( articles| stories)?:?|image (credit|source):.*|photo:.*|"
    r"this article (originally|first) appeared.*|all rights reserved.*)$",
    re.IGNORECASE,
)


def clean_text(text: str) -> str:
    if not text:
        return ""
    text = html.unescape(_TAG_RE.sub(" ", text))
    text = unicodedata.normalize("NFKC", text).replace("\r\n", "\n").replace("\r", "\n")
    lines: list[str] = []
    seen: set[str] = set()
    for raw in text.split("\n"):
        line = _WS_RE.sub(" ", raw).strip()
        if not line:
            if lines and lines[-1] != "":
                lines.append("")
            continue
        if _BOILERPLATE.match(line):
            continue
        key = line.lower()
        if len(line) > 40 and key in seen:  # repeated paragraphs from scrapers
            continue
        seen.add(key)
        lines.append(line)
    return "\n".join(lines).strip()
