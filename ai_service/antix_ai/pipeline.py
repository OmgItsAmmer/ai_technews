"""End-to-end ask pipeline: session -> rewrite -> plan -> retrieve -> context -> generate -> verify.

``ask_stream`` yields events (dicts):
  {"type": "status", "stage": ...}            progress
  {"type": "token", "text": ...}              answer text as it is generated
  {"type": "final", "answer", "citations", "grounding", "intent", "trace_id", "replaced"}
  {"type": "error", "message"}
``replaced`` is true when verification altered the streamed text; clients then swap in ``answer``.
"""

from __future__ import annotations

import logging
import re
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any
from zoneinfo import ZoneInfo

from pydantic import BaseModel, Field

from antix_ai.context.builder import build_context
from antix_ai.core.cache import stable_hash
from antix_ai.core.tracing import Trace, persist_trace
from antix_ai.generation import direct
from antix_ai.providers.base import ProviderError, ProviderUnavailable
from antix_ai.providers.offline import OfflineChat
from antix_ai.query.conversation import (
    Session,
    history_block,
    load_session,
    rewrite_standalone,
    save_turns,
)
from antix_ai.query.understanding import QueryPlan, understand
from antix_ai.retrieval.models import EvidenceArticle, RetrievalResult
from antix_ai.retrieval.service import retrieve
from antix_ai.runtime import Runtime
from antix_ai.verification.checks import Verdict, verify_answer

logger = logging.getLogger(__name__)

MAX_ANSWER_TOKENS = {"briefing": 900, "timeline": 900, "compare": 900}


class AskRequest(BaseModel):
    query: str = Field(min_length=1, max_length=2000)
    session_id: str | None = Field(default=None, max_length=128)
    timezone: str | None = None
    stream: bool = True


def _now(tz: str) -> tuple[datetime, str]:
    now = datetime.now(UTC)
    try:
        local = now.astimezone(ZoneInfo(tz))
    except Exception:
        local = now
    return now, local.strftime("%A, %B %d, %Y")


def _focus(plan: QueryPlan, articles: list[EvidenceArticle]) -> dict[str, Any]:
    return {
        "entities": plan.entities[:5],
        "story_ids": [a.story_id for a in articles if a.story_id][:4],
        "last_intent": plan.intent,
    }


def _citations(articles: list[EvidenceArticle], used: list[str]) -> list[dict]:
    by_sid = {a.sid: a for a in articles}
    ordered = [by_sid[s] for s in used if s in by_sid]
    return [a.citation() for a in ordered]


async def ask_stream(rt: Runtime, req: AskRequest, *, trace_kind: str = "ask") -> AsyncIterator[dict]:
    s = rt.settings
    tz = req.timezone or s.default_timezone
    trace = Trace(kind=trace_kind, query=req.query, session_id=req.session_id)
    usage = lambda role: (lambda model, i, o: trace.add_usage(role, model, i, o))  # noqa: E731
    answer, citations, verdict, plan = "", [], None, None

    try:
        session = await load_session(rt, req.session_id) if req.session_id else Session(id="")
        if req.session_id and not await rt.cache.allow(f"s:{req.session_id}", s.rate_limit_per_minute):
            yield {"type": "error", "message": "Too many requests. Please slow down."}
            return

        yield {"type": "status", "stage": "understanding"}
        with trace.stage("rewrite"):
            standalone = await rewrite_standalone(rt, req.query, session, usage("fast"))
        now, now_label = _now(tz)
        with trace.stage("plan"):
            plan = await understand(rt, req.query, standalone, tz=tz, now=now, usage_cb=usage("fast"))
        trace.set(plan=plan.model_dump())

        # --- no-retrieval intents
        if plan.intent in ("chit_chat", "out_of_scope"):
            answer = direct.CHIT_CHAT if plan.intent == "chit_chat" else direct.OUT_OF_SCOPE
            yield {"type": "token", "text": answer}
            result = RetrievalResult("none", [])
            verdict = None
        else:
            # answer cache (briefing / latest are the hot paths); keyed by corpus version
            cache_key = None
            if plan.intent in ("briefing", "latest") and not session.turns:
                ver = await rt.cache.corpus_version()
                cache_key = stable_hash("ans", plan.intent, plan.standalone_query, plan.time_range,
                                        plan.source_ids, ver, tz, now.date())
                if hit := await rt.cache.get_json("ans", cache_key):
                    trace.set(answer=hit["answer"], grounding=hit.get("grounding"), cache="hit")
                    yield {"type": "token", "text": hit["answer"]}
                    yield {**hit, "type": "final", "trace_id": trace.id, "replaced": False,
                           "cached": True}
                    await persist_trace(rt.db, trace)
                    await _remember(rt, session, req, hit["answer"], hit["citations"], plan, [], trace)
                    return

            yield {"type": "status", "stage": "searching"}
            with trace.stage("retrieve"):
                result = await retrieve(rt, plan, trace)
            if not result.articles:
                w = (result.coverage.get("window") or {}).get("label")
                answer = direct.no_evidence_message(w)
                yield {"type": "token", "text": answer}
            else:
                with trace.stage("context"):
                    ctx = build_context(
                        plan, result, history_block(session, 4),
                        budget_tokens=s.evidence_token_budget, now_label=now_label,
                    )
                trace.set(context_tokens=ctx.evidence_tokens)
                yield {"type": "status", "stage": "writing"}
                parts: list[str] = []
                extractive = False
                gen_started = trace.total_ms
                try:
                    async for tok in rt.providers.strong.stream(
                        ctx.messages,
                        max_tokens=MAX_ANSWER_TOKENS.get(plan.intent, 700),
                        temperature=0.1,
                        on_usage=usage("strong"),
                    ):
                        if not parts:
                            trace.mark("first_token")
                        parts.append(tok)
                        yield {"type": "token", "text": tok}
                    answer = "".join(parts).strip()
                except ProviderUnavailable:
                    extractive = True
                    answer = direct.extractive_answer(ctx.articles)
                    yield {"type": "token", "text": answer}
                except ProviderError as exc:
                    logger.error("generation failed: %s", exc)
                    if parts:  # partial answer: keep what the user saw, flag it
                        answer = "".join(parts).strip() + "\n\n_(The response was cut off.)_"
                    else:
                        extractive = True
                        answer = direct.extractive_answer(ctx.articles)
                        yield {"type": "token", "text": answer}
                trace.stages["generate"] = round(trace.total_ms - gen_started, 1)

                if extractive:  # service-authored text built from the evidence itself; nothing to verify
                    used = sorted(set(re.findall(r"\[(S\d+)\]", answer)), key=lambda x: int(x[1:]))
                    citations = _citations(ctx.articles, used)
                else:
                    with trace.stage("verify"):
                        verdict = await verify_answer(
                            answer, ctx.articles, fast=rt.providers.fast,
                            use_llm=s.verify_with_llm and plan.intent != "chit_chat",
                            usage_cb=usage("fast"),
                        )
                    if verdict.grounding < s.min_grounding and verdict.checks:
                        logger.warning("low grounding %.2f for trace %s", verdict.grounding, trace.id)
                    answer = verdict.answer or answer
                    citations = _citations(ctx.articles, verdict.used_sids)
                result = RetrievalResult(result.strategy, ctx.articles, result.coverage)

        replaced = bool(verdict and verdict.removed or (verdict and verdict.unknown_sids))
        trace.set(answer=answer, verdict=verdict.summary() if verdict else None,
                  grounding=verdict.grounding if verdict else None)
        final = {
            "type": "final",
            "answer": answer,
            "citations": citations,
            "grounding": verdict.grounding if verdict else None,
            "intent": plan.intent,
            "time_window": (plan.time_range or {}).get("label"),
            "trace_id": trace.id,
            "replaced": replaced,
        }
        yield final
        if cache_key_ok(plan, verdict, session) and result.articles:
            ver = await rt.cache.corpus_version()
            key = stable_hash("ans", plan.intent, plan.standalone_query, plan.time_range,
                              plan.source_ids, ver, tz, now.date())
            await rt.cache.set_json(
                "ans", key,
                {"answer": answer, "citations": citations, "grounding": final["grounding"],
                 "intent": plan.intent, "time_window": final["time_window"]},
                s.cache_answer_ttl,
            )
        await _remember(rt, session, req, answer, citations, plan, result.articles, trace)
    except Exception as exc:
        logger.exception("ask pipeline failed")
        trace.error = str(exc)[:500]
        yield {"type": "error", "message": "Something went wrong while answering. Please try again."}
    finally:
        await persist_trace(rt.db, trace)


def cache_key_ok(plan: QueryPlan | None, verdict: Verdict | None, session: Session) -> bool:
    return bool(
        plan and plan.intent in ("briefing", "latest") and not session.turns
        and verdict and verdict.grounding >= 0.8
    )


async def _remember(rt, session, req, answer, citations, plan, articles, trace) -> None:
    if not req.session_id:
        return
    try:
        await save_turns(rt, session, req.query, answer, citations, _focus(plan, articles), trace.id)
    except Exception as exc:
        logger.warning("could not persist conversation: %s", exc)


async def ask_sync(rt: Runtime, req: AskRequest) -> dict:
    final: dict | None = None
    err: str | None = None
    async for ev in ask_stream(rt, req, trace_kind="ask_sync"):
        if ev["type"] == "final":
            final = ev
        elif ev["type"] == "error":
            err = ev["message"]
    if final is None:
        raise RuntimeError(err or "no answer produced")
    final.pop("type", None)
    return final


__all__ = ["AskRequest", "ask_stream", "ask_sync", "OfflineChat"]
