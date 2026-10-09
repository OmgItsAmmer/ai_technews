"""arq worker: background ingestion, nightly reconcile."""

from __future__ import annotations

import logging
from typing import Any

from arq import cron
from arq.connections import RedisSettings

from antix_ai.config import get_settings
from antix_ai.core.logging import configure_logging
from antix_ai.ingestion.indexer import ingest_post, reconcile
from antix_ai.runtime import create_runtime

logger = logging.getLogger(__name__)


async def startup(ctx: dict[str, Any]) -> None:
    s = get_settings()
    configure_logging(s.log_level, s.log_json)
    ctx["rt"] = await create_runtime(s)


async def shutdown(ctx: dict[str, Any]) -> None:
    await ctx["rt"].close()


async def ingest_post_job(ctx: dict[str, Any], post_id: int, force: bool = False) -> dict:
    res = await ingest_post(ctx["rt"], post_id, force=force)
    if res.status == "failed":
        raise RuntimeError(res.error or "ingest failed")  # lets arq retry
    return res.__dict__


async def reconcile_job(ctx: dict[str, Any], days: int | None = None, force: bool = False) -> dict:
    report = await reconcile(ctx["rt"], days, force=force)
    logger.info("reconcile finished", extra={"data": report.__dict__})
    return report.__dict__


async def nightly_reconcile(ctx: dict[str, Any]) -> dict:
    return await reconcile_job(ctx, days=7, force=False)


class WorkerSettings:
    functions = [ingest_post_job, reconcile_job]
    cron_jobs = [cron(nightly_reconcile, hour={3}, minute={15}, run_at_startup=False)]
    on_startup = startup
    on_shutdown = shutdown
    max_tries = 3
    job_timeout = 600
    keep_result = 3600
    max_jobs = 4
    redis_settings = RedisSettings.from_dsn(get_settings().redis_url)
