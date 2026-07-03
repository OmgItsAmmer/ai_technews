"""In-memory fetch + Scrutinize embedding run state (Redis cache)."""

from __future__ import annotations

import uuid
from typing import Any

from django.core.cache import cache

from apps.frontend.scrutinize import ScrutinizeClient

FETCH_RUN_CACHE_PREFIX = "fetch_run:"
FETCH_RUN_TTL = 60 * 60


def _cache_key(run_id: str) -> str:
    return f"{FETCH_RUN_CACHE_PREFIX}{run_id}"


def create_fetch_run(*, sources_total: int) -> str:
    run_id = str(uuid.uuid4())
    cache.set(
        _cache_key(run_id),
        {
            "run_id": run_id,
            "phase": "fetching",
            "message": "Fetching latest news from sources…",
            "sources_total": sources_total,
            "sources_done": 0,
            "articles_saved": 0,
            "deleted_count": 0,
            "uploaded_count": 0,
            "embedding_total": 0,
            "embedding_done": 0,
            "embedding_failed": 0,
            "job_ids": [],
            "error": None,
        },
        FETCH_RUN_TTL,
    )
    return run_id


def get_fetch_run(run_id: str) -> dict[str, Any] | None:
    return cache.get(_cache_key(run_id))


def update_fetch_run(run_id: str, **fields: Any) -> dict[str, Any] | None:
    state = get_fetch_run(run_id)
    if state is None:
        return None
    state.update(fields)
    cache.set(_cache_key(run_id), state, FETCH_RUN_TTL)
    return state


def refresh_embedding_progress(run_id: str) -> dict[str, Any] | None:
    state = get_fetch_run(run_id)
    if state is None or state.get("phase") != "embedding":
        return state

    job_ids: list[str] = state.get("job_ids") or []
    if not job_ids:
        return update_fetch_run(
            run_id,
            phase="done",
            message="Fetch complete. No new articles needed embedding.",
        )

    client = ScrutinizeClient()
    done = failed = pending = 0
    for job_id in job_ids:
        job = client.get_job_status(job_id)
        if not job:
            pending += 1
            continue
        status = (job.get("status") or "").lower()
        if status == "done":
            done += 1
        elif status == "failed":
            failed += 1
        else:
            pending += 1

    fields: dict[str, Any] = {
        "embedding_done": done,
        "embedding_failed": failed,
        "embedding_total": len(job_ids),
        "message": f"Embedding articles for AI search ({done + failed}/{len(job_ids)})…",
    }
    if pending == 0:
        if failed and not done:
            fields["phase"] = "failed"
            fields["message"] = "Embedding failed for all uploaded articles."
            fields["error"] = "embedding_failed"
        else:
            fields["phase"] = "done"
            fields["message"] = "New articles indexed and ready for AI search."
    return update_fetch_run(run_id, **fields)
