"""Answers that need no retrieval, plus deterministic extractive fallbacks."""

from __future__ import annotations

from antix_ai.retrieval.models import EvidenceArticle

CHIT_CHAT = (
    "Hi! I'm Antix, the assistant for this AI & tech news site. Ask me what's new, "
    "for a recap of the week, or about a company, model or story, and I'll answer from our articles."
)
OUT_OF_SCOPE = (
    "I can only help with AI and technology news covered on this site. "
    "Try asking about a company, a model release, or what happened this week."
)
NO_EVIDENCE = (
    "I couldn't find articles on this in our database{window}. "
    "I'd rather not guess, so try rephrasing, widening the time range, or asking about a related topic."
)
UNAVAILABLE = "The AI engine is temporarily unavailable. Here are the most relevant articles I found:"


def no_evidence_message(window_label: str | None) -> str:
    return NO_EVIDENCE.format(window=f" for {window_label}" if window_label else "")


def extractive_answer(articles: list[EvidenceArticle], limit: int = 3) -> str:
    """Model-free answer: list the best articles' summaries with citation tags."""
    lines = [UNAVAILABLE]
    top = max((a.score for a in articles), default=0.0)
    picked = [a for a in articles if a.score >= 0.4 * top][:limit] or articles[:1]
    for a in picked:
        date = a.published_at.strftime("%b %d") if a.published_at else ""
        text = a.summary_short or (a.passages[0][:240] if a.passages else a.title)
        lines.append(f"- **{a.title}** ({a.source_name}, {date}): {text} [{a.sid}]")
    return "\n".join(lines)
