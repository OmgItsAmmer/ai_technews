"""Structure-aware chunking: paragraphs first, sentences when paragraphs are too long."""

from __future__ import annotations

import re
from dataclasses import dataclass

from antix_ai.core.tokens import count_tokens

# Split after . ! ? when followed by whitespace + capital/quote/digit,
# but not after common abbreviations or single initials (U.S., e.g., Mr.)
_ABBREV = (
    r"(?<!\b[A-Z]\.)(?<!\bMr\.)(?<!\bMs\.)(?<!\bDr\.)(?<!\bvs\.)(?<!\bSt\.)"
    r"(?<!\be\.g\.)(?<!\bi\.e\.)(?<!\bInc\.)(?<!\bCo\.)(?<!\bCorp\.)"
)
_SENT_RE = re.compile(r"(?<=[.!?])" + _ABBREV + r"[\"')\]]?\s+(?=[\"'(\[A-Z0-9])")


def split_sentences(text: str) -> list[str]:
    return [s.strip() for s in _SENT_RE.split(text) if s.strip()]


@dataclass
class Chunk:
    ord: int
    text: str
    token_count: int


def chunk_text(text: str, target_tokens: int = 420, overlap_tokens: int = 60) -> list[Chunk]:
    text = text.strip()
    if not text:
        return []
    total = count_tokens(text)
    if total <= int(target_tokens * 1.4):
        return [Chunk(0, text, total)]

    # Units: paragraphs, or sentences of oversized paragraphs
    units: list[str] = []
    for para in (p.strip() for p in text.split("\n")):
        if not para:
            continue
        if count_tokens(para) > target_tokens:
            units.extend(split_sentences(para))
        else:
            units.append(para)

    chunks: list[Chunk] = []
    current: list[str] = []
    cur_tokens = 0
    for unit in units:
        ut = count_tokens(unit)
        if current and cur_tokens + ut > target_tokens:
            body = "\n".join(current)
            chunks.append(Chunk(len(chunks), body, count_tokens(body)))
            # overlap: carry trailing units up to overlap_tokens
            carry: list[str] = []
            carry_tokens = 0
            for prev in reversed(current):
                pt = count_tokens(prev)
                if carry_tokens + pt > overlap_tokens:
                    break
                carry.insert(0, prev)
                carry_tokens += pt
            current, cur_tokens = carry, carry_tokens
        current.append(unit)
        cur_tokens += ut
    if current:
        body = "\n".join(current)
        # merge a tiny tail into the previous chunk
        if chunks and count_tokens(body) < target_tokens // 4:
            prev = chunks.pop()
            body = prev.text + "\n" + body
        chunks.append(Chunk(len(chunks), body, count_tokens(body)))
    return chunks
