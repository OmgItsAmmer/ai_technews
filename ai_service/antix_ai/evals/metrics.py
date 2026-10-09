"""Backend-agnostic eval metrics. Computed identically for the new service and Scrutinize."""

from __future__ import annotations

import re
import statistics
from dataclasses import dataclass, field
from datetime import datetime

from antix_ai.verification.checks import _NUM

REFUSAL_RE = re.compile(
    r"(couldn'?t find|could not find|can'?t find|no (relevant )?(articles|information|mention|results)|"
    r"don'?t (have|contain)|do not (have|contain)|not (mentioned|covered|available|in (the|our))|"
    r"unable to (find|answer)|no data|isn'?t (covered|mentioned)|aren'?t any|there (are|is) no|"
    r"insufficient|not enough information|only help with|can only help)",
    re.I,
)


@dataclass
class CaseResult:
    id: str
    kind: str
    question: str
    answer: str = ""
    cited_post_ids: list[int] = field(default_factory=list)
    retrieved_post_ids: list[int] = field(default_factory=list)
    cited_dates: list[datetime] = field(default_factory=list)
    latency_ms: float = 0.0
    first_token_ms: float | None = None
    error: str | None = None
    # filled by score()
    scores: dict[str, float | None] = field(default_factory=dict)


def refused(answer: str) -> bool:
    return bool(REFUSAL_RE.search(answer or ""))


_DATE_RE = re.compile(
    r"\b(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s+\d{1,2}(?:,?\s+\d{4})?\b|\b\d{4}-\d{2}-\d{2}\b",
    re.I,
)


def numbers_in(text: str) -> set[str]:
    out = set()
    # dates are scored by the temporal metric; formatted dates added by the service are not claims
    for m in _NUM.finditer(_DATE_RE.sub(" ", text or "")):
        digits = re.sub(r"\D", "", m.group(0))
        if len(digits) >= 2:  # ignore single digits ("3 bullets", list numbering)
            out.add(digits)
    return out


def score_case(case: dict, res: CaseResult, evidence_text: str) -> None:
    kind = case["kind"]
    exp = set(case.get("expected_post_ids", []))
    cited, retrieved = set(res.cited_post_ids), set(res.retrieved_post_ids)
    s: dict[str, float | None] = {}

    if res.error:
        res.scores = {"error": 1.0}
        return

    # Retrieval: did we surface the right article(s)?
    s["recall"] = (len(exp & (retrieved | cited)) / len(exp)) if exp else None
    # Citation precision: cited articles that are actually relevant
    s["citation_precision"] = (len(cited & exp) / len(cited)) if (exp and cited) else (0.0 if exp else None)
    # Answered with at least one citation when there is evidence
    s["cited"] = (1.0 if cited else 0.0) if exp else None

    # Numeric faithfulness: numbers in the answer must exist in the evidence text
    nums = numbers_in(re.sub(r"\[S\d+\]", "", res.answer))
    if nums and kind not in ("unanswerable",) and not (refused(res.answer) and not cited):
        ev = re.sub(r"\D", "", evidence_text or "") + " " + " ".join(numbers_in(evidence_text or ""))
        grounded = sum(1 for n in nums if n in ev)
        s["numeric_faithfulness"] = grounded / len(nums)
    else:
        s["numeric_faithfulness"] = None

    # Refusal behaviour
    if kind == "unanswerable":
        s["correct_refusal"] = 1.0 if (refused(res.answer) and not cited) else 0.0
        s["hallucinated_on_unanswerable"] = 1.0 if (not refused(res.answer)) else 0.0
    elif kind in ("fact_lookup", "entity_overview", "compare", "timeline"):
        s["false_refusal"] = 1.0 if refused(res.answer) and not cited else 0.0

    # Temporal correctness: every cited article must be inside the question's window
    win = case.get("window")
    if win and res.cited_dates:
        lo, hi = datetime.fromisoformat(win["from"]), datetime.fromisoformat(win["to"])
        inside = [lo <= d < hi for d in res.cited_dates]
        s["temporal_correct"] = sum(inside) / len(inside)
    elif win and kind == "time_trap":
        s["temporal_correct"] = 1.0 if (not res.cited_dates) else 0.0

    must_not = set(case.get("must_not_cite", []))
    if must_not:
        s["no_forbidden_citation"] = 0.0 if (cited & must_not) else 1.0
    kw = case.get("expected_keywords") or []
    if kw:
        low = res.answer.lower()
        s["keyword_hit"] = sum(1 for k in kw if k.lower() in low) / len(kw)
    res.scores = s


def aggregate(results: list[CaseResult]) -> dict:
    metrics: dict[str, list[float]] = {}
    for r in results:
        for k, v in r.scores.items():
            if v is not None:
                metrics.setdefault(k, []).append(v)
    agg = {k: round(statistics.fmean(v), 4) for k, v in metrics.items()}
    lat = sorted(r.latency_ms for r in results if r.latency_ms)
    if lat:
        agg["latency_p50_ms"] = round(lat[len(lat) // 2], 1)
        agg["latency_p95_ms"] = round(lat[min(len(lat) - 1, int(len(lat) * 0.95))], 1)
    ft = sorted(r.first_token_ms for r in results if r.first_token_ms)
    if ft:
        agg["first_token_p50_ms"] = round(ft[len(ft) // 2], 1)
    agg["errors"] = sum(1 for r in results if r.error)
    agg["cases"] = len(results)
    by_kind: dict[str, int] = {}
    for r in results:
        by_kind[r.kind] = by_kind.get(r.kind, 0) + 1
    agg["by_kind"] = by_kind
    return agg
