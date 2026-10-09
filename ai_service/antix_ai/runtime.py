"""Process-wide runtime: settings, DB pool, cache, providers. Shared by API, worker and CLI."""

from __future__ import annotations

from dataclasses import dataclass

from redis.asyncio import Redis

from antix_ai.config import Settings, get_settings
from antix_ai.core.cache import Cache
from antix_ai.core.db import Database
from antix_ai.providers.registry import Providers, build_providers


@dataclass
class Runtime:
    settings: Settings
    db: Database
    cache: Cache
    providers: Providers

    async def close(self) -> None:
        await self.db.close()
        await self.cache.redis.aclose()


async def create_runtime(settings: Settings | None = None, providers: Providers | None = None) -> Runtime:
    s = settings or get_settings()
    db = Database(s.database_url, s.db_pool_min, s.db_pool_max, s.hnsw_ef_search)
    await db.open()
    redis = Redis.from_url(s.redis_url, decode_responses=True, socket_timeout=2.0)
    return Runtime(settings=s, db=db, cache=Cache(redis), providers=providers or build_providers(s))
