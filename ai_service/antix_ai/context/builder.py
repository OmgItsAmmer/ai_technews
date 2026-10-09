"""Context builder: token-budgeted, article-grouped evidence with coverage notes."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from antix_ai import prompts
from antix_ai.core.tokens import count_tokens, truncate_tokens
from antix_ai.providers.base import Message
from antix_ai.query.understanding import QueryPlan
from antix_ai.retrieval.models import EvidenceArticle, RetrievalResult
from antix_ai.retrieval.relevance import name_tokens

STYLE = {
    "bullets": "Use short bullet points.",
    "paragraph": "Answer in 1-3 short paragraphs.",
    "table": "Use a compact markdown table where it helps, then a one-line takeaway.",
    "timeline": "Use a dated list, oldest first, one line per event.",
}
# evidence token budget multipliers per intent
BUDGET_SCALE = {"briefing": 1.2, "timeline": 1.1, "compare": 1.2, "fact_lookup": 0.8}


@dataclass
class BuiltContext:
    messages: list[Message]
    articles: list[EvidenceArticle]
    evidence_tokens: int
    coverage_notes: list[str]


def _fmt_date(d: datetime | None) -> str:
    return d.strftime("%Y-%m-%d") if d else "undated"


def coverage_notes(plan: QueryPlan, result: RetrievalResult) -> list[str]:
    cov, notes = result.coverage, []
    w = cov.get("window")
    if w:
        notes.append(f"Time window applied: {w.get('label')} ({w['from'][:10]} to {w['to'][:10]}).")
    if cov.get("relaxed"):
        notes.append(f"Note: few matches, so the search was relaxed ({cov['relaxed']}).")
    inw = cov.get("articles_in_window")
    if inw is not None:
        notes.append(f"The database has {inw} article(s) in this window"
                     + (f" from {', '.join(plan.source_names)}." if plan.source_names else "."))
    n = len(result.articles)
    if n == 0:
        notes.append("No relevant articles were found for this question.")
    elif n <= 2:
        notes.append(f"Only {n} relevant article(s) were found; coverage is thin.")
    if n and cov.get("distinct_sources", 0) == 1:
        notes.append("All relevant articles come from a single outlet.")
    if plan.entities and n:
        hay = " ".join(
            f"{a.title} {a.summary_short} {' '.join(a.passages)}" for a in result.articles
        ).lower()
        missing = [
            e for e in plan.entities[:5]
            if (toks := name_tokens(e)) and not any(t in hay for t in toks)
        ]
        found = [e for e in plan.entities[:5] if e not in missing]
        if found:
            notes.append(f"Entities of interest: {', '.join(found)}.")
        if missing:
            notes.append(
                f"No articles in the database mention: {', '.join(missing)}. "
                "Say so explicitly instead of answering about them."
            )
    return notes


def _article_block(a: EvidenceArticle, passage_tokens: int, with_facts: bool) -> str:
    head = f"[{a.sid}] {a.source_name or 'Unknown source'} · {_fmt_date(a.published_at)} · {a.title}"
    meta = []
    if a.story_sources > 1:
        meta.append(f"reported by {a.story_sources} outlets")
    if a.content_type in ("rumor", "opinion", "press_release"):
        meta.append(f"type: {a.content_type}")
    if meta:
        head += f" ({'; '.join(meta)})"
    lines = [head]
    if a.summary_short:
        lines.append(f"Summary: {a.summary_short}")
    if with_facts and a.key_facts:
        lines.append("Key facts: " + " | ".join(f["fact"] for f in a.key_facts[:5]))
    for p in a.passages:
        lines.append(truncate_tokens(p.strip(), passage_tokens))
    return "\n".join(lines)


def order_for_attention(blocks: list[tuple[EvidenceArticle, str]], intent: str) -> list:
    """Models attend best to the start and end of context: put strongest evidence there."""
    if intent in ("timeline",) or len(blocks) < 4:
        return blocks
    ranked = sorted(blocks, key=lambda b: b[0].score, reverse=True)
    front, back = [], []
    for i, b in enumerate(ranked):
        (front if i % 2 == 0 else back).append(b)
    return front + back[::-1]


def build_context(
    plan: QueryPlan,
    result: RetrievalResult,
    history: str,
    *,
    budget_tokens: int,
    now_label: str,
) -> BuiltContext:
    articles = list(result.articles)
    budget = int(budget_tokens * BUDGET_SCALE.get(plan.intent, 1.0))
    n = max(1, len(articles))
    passage_tokens = max(120, min(450, budget // n - 160))

    # Fit within budget: drop lowest-ranked articles first, then drop key facts
    def render(arts: list[EvidenceArticle], facts: bool) -> list[tuple[EvidenceArticle, str]]:
        return [(a, _article_block(a, passage_tokens, facts)) for a in arts]

    keep = list(articles)
    for a_i, a in enumerate(keep, start=1):
        a.sid = f"S{a_i}"
    blocks = render(keep, True)
    total = sum(count_tokens(b) for _, b in blocks)
    while total > budget and len(keep) > 1:
        victim = min(keep, key=lambda a: a.score)
        keep.remove(victim)
        for a_i, a in enumerate(keep, start=1):
            a.sid = f"S{a_i}"
        blocks = render(keep, True)
        total = sum(count_tokens(b) for _, b in blocks)
    if total > budget:
        blocks = render(keep, False)
        total = sum(count_tokens(b) for _, b in blocks)

    notes = coverage_notes(plan, result)
    ordered = order_for_attention(blocks, plan.intent)
    evidence = "\n\n".join(b for _, b in ordered) or "(no articles)"

    template = "briefing" if plan.intent == "briefing" else "answer"
    system = prompts.load(template).format(
        today=now_label, style=STYLE.get(plan.answer_shape, STYLE["paragraph"])
    )
    user_parts = []
    if history:
        user_parts.append(f"CONVERSATION CONTEXT:\n{history}")
    user_parts.append("COVERAGE NOTES:\n" + "\n".join(f"- {n}" for n in notes))
    user_parts.append(f"EVIDENCE:\n{evidence}")
    user_parts.append(f"QUESTION: {plan.standalone_query}")
    return BuiltContext(
        messages=[Message("system", system), Message("user", "\n\n".join(user_parts))],
        articles=keep,
        evidence_tokens=total,
        coverage_notes=notes,
    )
