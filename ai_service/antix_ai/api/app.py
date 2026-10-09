"""FastAPI application."""

from __future__ import annotations

import json
import logging
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass

from arq import create_pool
from arq.connections import ArqRedis, RedisSettings
from fastapi import APIRouter, Depends, FastAPI, HTTPException, Query, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

from antix_ai import features
from antix_ai.config import Settings, get_settings
from antix_ai.core.auth import require_service_key
from antix_ai.core.logging import configure_logging
from antix_ai.ingestion.indexer import ingest_post
from antix_ai.pipeline import AskRequest, ask_stream, ask_sync
from antix_ai.runtime import Runtime, create_runtime

logger = logging.getLogger(__name__)


@dataclass
class AppContext:
    settings: Settings
    rt: Runtime
    queue: ArqRedis | None


def create_app(runtime: Runtime | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        settings = runtime.settings if runtime else get_settings()
        configure_logging(settings.log_level, settings.log_json)
        rt = runtime or await create_runtime(settings)
        queue = None
        try:
            queue = await create_pool(RedisSettings.from_dsn(settings.redis_url))
        except Exception as exc:
            logger.warning("job queue unavailable, ingest will run inline: %s", exc)
        app.state.ctx = AppContext(settings, rt, queue)
        yield
        if queue:
            await queue.aclose()
        if runtime is None:
            await rt.close()

    app = FastAPI(title="Antix News AI", version="0.1.0", lifespan=lifespan)

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception):
        logger.exception("unhandled error on %s", request.url.path)
        return JSONResponse({"error": "internal_error"}, status_code=500)

    app.include_router(public)
    app.include_router(v1, prefix="/v1", dependencies=[Depends(require_service_key)])
    return app


def ctx(request: Request) -> AppContext:
    return request.app.state.ctx


def get_rt(request: Request) -> Runtime:
    return request.app.state.ctx.rt


# ------------------------------------------------------------------ public

public = APIRouter()


@public.get("/health")
async def health() -> dict:
    return {"status": "ok"}


@public.get("/ready")
async def ready(request: Request):
    rt = get_rt(request)
    checks = {"database": False, "redis": await rt.cache.ping()}
    try:
        checks["database"] = await rt.db.ping()
    except Exception:
        pass
    ok = all(checks.values())
    return JSONResponse({"status": "ready" if ok else "degraded", **checks}, status_code=200 if ok else 503)


# --------------------------------------------------------------------- v1

v1 = APIRouter()


def _sse(event: dict) -> bytes:
    return f"event: {event['type']}\ndata: {json.dumps(event, default=str)}\n\n".encode()


@v1.post("/ask")
async def ask(req: AskRequest, request: Request):
    rt = get_rt(request)
    if not req.stream:
        try:
            return await ask_sync(rt, req)
        except RuntimeError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

    async def gen() -> AsyncIterator[bytes]:
        async for ev in ask_stream(rt, req):
            yield _sse(ev)
        yield b"event: end\ndata: {}\n\n"

    return StreamingResponse(
        gen(), media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@v1.post("/ask/sync")
async def ask_sync_endpoint(req: AskRequest, request: Request):
    try:
        return await ask_sync(get_rt(request), req)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


class ReconcileRequest(BaseModel):
    days: int | None = Field(default=None, ge=1, le=730)
    force: bool = False


@v1.post("/ingest/reconcile")
async def reconcile_endpoint(body: ReconcileRequest, request: Request):
    c = ctx(request)
    if not c.queue:
        raise HTTPException(status_code=503, detail="job queue unavailable")
    job = await c.queue.enqueue_job("reconcile_job", body.days, body.force)
    return {"queued": True, "job_id": job.job_id if job else None}


class IngestResponse(BaseModel):
    post_id: int
    status: str
    queued: bool = False
    chunks: int = 0
    error: str | None = None


@v1.post("/ingest/{post_id}", response_model=IngestResponse)
async def ingest(post_id: int, request: Request, force: bool = False, wait: bool = False):
    c = ctx(request)
    if c.queue and not wait:
        await c.queue.enqueue_job(
            "ingest_post_job", post_id, force,
            _job_id=f"ingest:{post_id}:{uuid.uuid4().hex[:8]}",
        )
        return IngestResponse(post_id=post_id, status="queued", queued=True)
    res = await ingest_post(c.rt, post_id, force=force)
    return IngestResponse(post_id=post_id, status=res.status, chunks=res.chunks, error=res.error)


@v1.get("/briefing")
async def briefing(
    request: Request, range: str = Query("today", max_length=60), tz: str | None = None,
    limit: int = Query(10, ge=1, le=30),
):
    return await features.briefing(get_rt(request), range, tz, limit)


@v1.get("/posts/{post_id}/related")
async def related(post_id: int, request: Request, limit: int = Query(6, ge=1, le=20)):
    return {"post_id": post_id, "related": await features.related(get_rt(request), post_id, limit)}


@v1.get("/stories/{story_id}")
async def story(story_id: int, request: Request):
    res = await features.story(get_rt(request), story_id)
    if res is None:
        raise HTTPException(status_code=404, detail="story not found")
    return res


@v1.get("/trending")
async def trending(request: Request, days: int = Query(7, ge=1, le=60), limit: int = Query(15, ge=1, le=50)):
    return {"days": days, "entities": await features.trending(get_rt(request), days, limit)}


class FeedbackBody(BaseModel):
    trace_id: uuid.UUID
    rating: int = Field(ge=-1, le=1)
    note: str | None = Field(default=None, max_length=1000)


@v1.post("/feedback")
async def feedback(body: FeedbackBody, request: Request):
    rt = get_rt(request)
    await rt.db.execute(
        "UPDATE ai.trace SET feedback = %s, feedback_note = %s WHERE id = %s",
        (body.rating, body.note, str(body.trace_id)),
    )
    return {"ok": True}


class ShadowBody(BaseModel):
    query: str = Field(min_length=1, max_length=2000)
    answer: str = Field(max_length=20000)
    cited_post_ids: list[int] = Field(default_factory=list)
    latency_ms: float = 0.0
    backend: str = Field(default="scrutinize", max_length=32)


@v1.post("/shadow")
async def shadow(body: ShadowBody, request: Request):
    """Record what the legacy backend answered, so it can be compared with this service."""
    rt = get_rt(request)
    await rt.db.execute(
        """INSERT INTO ai.trace (id, kind, backend, query, answer, retrieved, latency)
           VALUES (%s, 'shadow', %s, %s, %s, %s, %s)""",
        (str(uuid.uuid4()), body.backend, body.query, body.answer,
         json.dumps([{"post_id": p} for p in body.cited_post_ids]),
         json.dumps({"total": body.latency_ms})),
    )
    return {"ok": True}


@v1.get("/conversations/{session_id}")
async def conversation(session_id: str, request: Request):
    rt = get_rt(request)
    rows = await rt.db.fetch(
        "SELECT role, content, citations, trace_id::text AS trace_id, created_at "
        "FROM ai.message WHERE conversation_id = %s ORDER BY id",
        (session_id,),
    )
    return {"session_id": session_id, "messages": rows}


@v1.delete("/conversations/{session_id}")
async def clear_conversation(session_id: str, request: Request):
    rt = get_rt(request)
    await rt.db.execute("DELETE FROM ai.conversation WHERE id = %s", (session_id,))
    await rt.cache.redis.delete(f"antix_ai:session:{session_id}")
    return {"ok": True}


# ------------------------------------------------------------------- admin


@v1.get("/admin/stats")
async def admin_stats(request: Request):
    return await features.stats(get_rt(request))


@v1.get("/admin/traces")
async def admin_traces(
    request: Request, limit: int = Query(50, ge=1, le=200), low_grounding: bool = False,
    negative_feedback: bool = False,
):
    rt = get_rt(request)
    where = ["TRUE"]
    if low_grounding:
        where.append(f"grounding < {rt.settings.min_grounding}")
    if negative_feedback:
        where.append("feedback < 0")
    rows = await rt.db.fetch(
        f"SELECT id::text, kind, backend, query, left(answer, 400) AS answer, grounding, feedback, "
        f"latency, created_at FROM ai.trace WHERE {' AND '.join(where)} "
        f"ORDER BY created_at DESC LIMIT %s",
        (limit,),
    )
    return {"traces": rows}


@v1.get("/admin/traces/{trace_id}")
async def admin_trace(trace_id: uuid.UUID, request: Request):
    row = await get_rt(request).db.fetchrow(
        "SELECT *, id::text AS id FROM ai.trace WHERE id = %s", (str(trace_id),)
    )
    if not row:
        raise HTTPException(status_code=404, detail="trace not found")
    return row


class RetrieveBody(BaseModel):
    query: str = Field(min_length=1, max_length=2000)
    timezone: str | None = None


@v1.post("/admin/retrieve")
async def admin_retrieve(body: RetrieveBody, request: Request):
    """Debug: show the plan and ranked evidence without generating an answer."""
    from datetime import UTC, datetime

    from antix_ai.query.understanding import understand
    from antix_ai.retrieval.service import retrieve

    rt = get_rt(request)
    plan = await understand(rt, body.query, body.query, tz=body.timezone, now=datetime.now(UTC))
    result = await retrieve(rt, plan)
    return {
        "plan": plan.model_dump(),
        "strategy": result.strategy,
        "coverage": result.coverage,
        "articles": [
            {"post_id": a.post_id, "title": a.title, "source": a.source_name,
             "date": a.published_at, "score": a.score, "story_id": a.story_id,
             "passages": [p[:300] for p in a.passages]}
            for a in result.articles
        ],
    }
