"""Post-generation verification: citation integrity, uncited claims, temporal and claim support."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

from pydantic import BaseModel

from antix_ai import prompts
from antix_ai.ingestion.chunker import split_sentences
from antix_ai.providers.base import ChatModel, Message, ProviderError
from antix_ai.providers.offline import OfflineChat
from antix_ai.providers.structured import complete_structured
from antix_ai.retrieval.models import EvidenceArticle

logger = logging.getLogger(__name__)

CITE_RE = re.compile(r"\[(S\d+)\]")
_CLAIM_SIGNAL = re.compile(
    r"(\d|\$|%|\b(announced|launched|released|acquired|raised|said|says|reported|will|plans|"
    r"unveiled|introduced|banned|fined|sued|according)\b)",
    re.I,
)
_NUM = re.compile(r"\$?\d[\d,]*(?:\.\d+)?\s?(?:%|percent|million|billion|trillion|bn|m|k|x)?", re.I)
_MONTH_DATE = re.compile(
    r"\b(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|aug(?:ust)?|"
    r"sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)\.?\s+(\d{1,2})\b",
    re.I,
)
# Calendar dates ("October 8, 2026", "Oct 8", "2026-10-08") come from article metadata, not its body;
# they are validated by temporal_issues(), so the number check must not treat them as claims.
_DATE_PHRASE = re.compile(
    r"\b(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s+\d{1,2}(?:st|nd|rd|th)?(?:,?\s+\d{4})?\b"
    r"|\b\d{1,2}(?:st|nd|rd|th)?\s+(?:of\s+)?(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?(?:,?\s+\d{4})?\b"
    r"|\b\d{4}-\d{2}-\d{2}\b",
    re.I,
)
_META_SENTENCE = re.compile(
    r"^(background:|i (couldn't|could not|can't|don't|do not)|the (articles|evidence|database|sources)|"
    r"there (are|is) (no|only)|none of|no (articles|information)|sorry)",
    re.I,
)
MONTH_NUM = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], start=1)}


@dataclass
class ClaimCheck:
    sentence: str
    sids: list[str]
    verdict: str  # supported | partial | unsupported | uncited | unchecked
    reason: str = ""


@dataclass
class Verdict:
    answer: str
    grounding: float
    checks: list[ClaimCheck] = field(default_factory=list)
    unknown_sids: list[str] = field(default_factory=list)
    uncited: list[str] = field(default_factory=list)
    temporal_issues: list[str] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)
    used_sids: list[str] = field(default_factory=list)
    llm_checked: bool = False

    def summary(self) -> dict:
        return {
            "grounding": self.grounding,
            "unknown_sids": self.unknown_sids,
            "uncited": self.uncited[:5],
            "temporal_issues": self.temporal_issues[:5],
            "removed": self.removed[:5],
            "llm_checked": self.llm_checked,
            "claims": [c.__dict__ for c in self.checks][:20],
        }


def strip_unknown_citations(answer: str, valid: set[str]) -> tuple[str, list[str]]:
    unknown = sorted({m for m in CITE_RE.findall(answer) if m not in valid})
    if unknown:
        answer = CITE_RE.sub(lambda m: m.group(0) if m.group(1) in valid else "", answer)
        answer = re.sub(r"[ \t]+([.,;:])", r"\1", re.sub(r" {2,}", " ", answer))
    return answer, unknown


def _is_claim(sentence: str) -> bool:
    s = sentence.strip()
    if len(s) < 25 or s.endswith("?") or _META_SENTENCE.match(s.lstrip("-*• ")):
        return False
    return bool(_CLAIM_SIGNAL.search(s))


def find_uncited(answer: str) -> list[str]:
    bad = []
    for line in answer.split("\n"):
        for sent in split_sentences(line):
            if _is_claim(sent) and not CITE_RE.search(sent):
                # tolerate a bullet whose citation is at the end of the *next* clause on the same line
                bad.append(sent)
    return bad


def _numbers(text: str) -> set[str]:
    return {re.sub(r"[,\s]", "", n.group(0).lower()).rstrip(".") for n in _NUM.finditer(text)
            if any(ch.isdigit() for ch in n.group(0))}


def number_support(sentence: str, sources_text: str) -> bool:
    """Every number in the sentence (ignoring citation tags / tiny ints) appears in a cited source."""
    sentence = _DATE_PHRASE.sub(" ", CITE_RE.sub("", sentence))
    nums = _numbers(sentence)
    src = _numbers(sources_text)
    src_plain = re.sub(r"[,\s]", "", sources_text.lower())
    for n in nums:
        digits = re.sub(r"\D", "", n)
        if len(digits) <= 1:
            continue
        if n in src or n.rstrip("%mbkx") in src_plain or digits in src_plain:
            continue
        return False
    return True


def temporal_issues(sentence: str, sids: list[str], by_sid: dict[str, EvidenceArticle]) -> list[str]:
    """A dated claim must fall on/after the cited article's publication (events can't precede
    reporting by more than the article's lookback; we flag dates AFTER the article date)."""
    issues = []
    for m in _MONTH_DATE.finditer(sentence):
        mon = MONTH_NUM[m.group(1).lower()[:3]]
        day = int(m.group(2))
        for sid in sids:
            a = by_sid.get(sid)
            if not a or not a.published_at:
                continue
            pub = a.published_at
            if (mon, day) > (pub.month, pub.day) and (mon - pub.month) % 12 <= 6:
                issues.append(f"'{m.group(0)}' is after {sid}'s publication date {pub.date()}")
    return issues


class _Verdicts(BaseModel):
    class Item(BaseModel):
        id: int
        verdict: str
        reason: str = ""

    verdicts: list[Item]


async def llm_support(
    model: ChatModel, claims: list[tuple[str, list[str]]], by_sid: dict[str, EvidenceArticle], usage_cb=None
) -> dict[int, tuple[str, str]]:
    blocks = []
    for i, (sent, sids) in enumerate(claims):
        src = "\n".join(
            f"[{sid}] {by_sid[sid].title}. {by_sid[sid].summary_short} "
            f"{' '.join(by_sid[sid].passages)[:1500]} "
            f"{' '.join(f['fact'] for f in by_sid[sid].key_facts)}"
            for sid in sids if sid in by_sid
        )
        blocks.append(f"CLAIM {i}: {CITE_RE.sub('', sent).strip()}\nSOURCE:\n{src}")
    res = await complete_structured(
        model,
        [Message("system", prompts.load("verify")), Message("user", "\n\n".join(blocks))],
        _Verdicts,
        max_tokens=60 * len(claims) + 100,
        usage_cb=usage_cb,
    )
    return {v.id: (v.verdict.lower(), v.reason) for v in res.verdicts}


def _source_text(a: EvidenceArticle) -> str:
    date = f"{a.published_at:%Y-%m-%d %B %d %Y}" if a.published_at else ""
    return (f"{a.title} {a.summary_short} {' '.join(a.passages)} "
            f"{' '.join(f['fact'] for f in a.key_facts)} {date}")


async def verify_answer(
    answer: str,
    articles: list[EvidenceArticle],
    *,
    fast: ChatModel,
    use_llm: bool,
    usage_cb=None,
    max_llm_claims: int = 8,
) -> Verdict:
    by_sid = {a.sid: a for a in articles}
    answer, unknown = strip_unknown_citations(answer, set(by_sid))
    uncited = find_uncited(answer)

    checks: list[ClaimCheck] = []
    llm_candidates: list[tuple[int, str, list[str]]] = []
    t_issues: list[str] = []
    for line in answer.split("\n"):
        for sent in split_sentences(line):
            sids = CITE_RE.findall(sent)
            if not sids or not _is_claim(sent):
                continue
            src_text = " ".join(_source_text(by_sid[s]) for s in sids if s in by_sid)
            issues = temporal_issues(sent, sids, by_sid)
            t_issues += issues
            if not number_support(sent, src_text):
                checks.append(ClaimCheck(sent, sids, "unsupported", "number not found in cited source"))
            elif issues:
                checks.append(ClaimCheck(sent, sids, "partial", issues[0]))
            else:
                idx = len(checks)
                checks.append(ClaimCheck(sent, sids, "unchecked"))
                llm_candidates.append((idx, sent, sids))

    llm_checked = False
    if use_llm and llm_candidates and not isinstance(fast, OfflineChat):
        batch = llm_candidates[:max_llm_claims]
        try:
            res = await llm_support(fast, [(s, sids) for _, s, sids in batch], by_sid, usage_cb)
            for pos, (idx, _, _) in enumerate(batch):
                if pos in res:
                    v, reason = res[pos]
                    checks[idx].verdict = v if v in ("supported", "partial", "unsupported") else "partial"
                    checks[idx].reason = reason
            llm_checked = True
        except ProviderError as exc:
            logger.info("claim verifier unavailable: %s", exc)

    for c in checks:
        if c.verdict == "unchecked":
            c.verdict = "supported"  # passed deterministic checks, not LLM-verified

    removed: list[str] = []
    for c in checks:
        if c.verdict == "unsupported":
            answer = answer.replace(c.sentence, "").strip()
            removed.append(c.sentence)
    answer = re.sub(r"\n{3,}", "\n\n", re.sub(r"(?m)^\s*[-*•]\s*$", "", answer)).strip()

    weights = {"supported": 1.0, "partial": 0.5, "unsupported": 0.0}
    claim_total = len(checks) + len(uncited)
    if claim_total == 0:
        grounding = 1.0
    else:
        score = sum(weights[c.verdict] for c in checks)
        grounding = round(score / claim_total, 3)
    if unknown:
        grounding = round(grounding * 0.8, 3)

    return Verdict(
        answer=answer,
        grounding=grounding,
        checks=checks,
        unknown_sids=unknown,
        uncited=uncited,
        temporal_issues=t_issues,
        removed=removed,
        used_sids=sorted(set(CITE_RE.findall(answer)), key=lambda s: int(s[1:])),
        llm_checked=llm_checked,
    )
