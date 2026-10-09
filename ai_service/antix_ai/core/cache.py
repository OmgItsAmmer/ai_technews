"""Redis-backed caching, corpus versioning and rate limiting.

Every cache that can contain news content is keyed by ``corpus_version``, which is
bumped on each ingest. That makes stale answers structurally impossible.
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from typing import Any

from redis.asyncio import Redis

logger = logging.getLogger(__name__)

CORPUS_VERSION_KEY = "antix_ai:corpus_version"


def stable_hash(*parts: Any) -> str:
    raw = json.dumps(parts, sort_keys=True, default=str, ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]


class Cache:
    def __init__(self, redis: Redis, prefix: str = "antix_ai"):
        self.redis = redis
        self.prefix = prefix

    def _k(self, namespace: str, key: str) -> str:
        return f"{self.prefix}:{namespace}:{key}"

    async def get_json(self, namespace: str, key: str) -> Any | None:
        try:
            raw = await self.redis.get(self._k(namespace, key))
        except Exception as exc:  # cache must never break requests
            logger.warning("cache get failed: %s", exc)
            return None
        return json.loads(raw) if raw else None

    async def set_json(self, namespace: str, key: str, value: Any, ttl: int) -> None:
        try:
            await self.redis.set(self._k(namespace, key), json.dumps(value, default=str), ex=ttl)
        except Exception as exc:
            logger.warning("cache set failed: %s", exc)

    async def corpus_version(self) -> int:
        try:
            return int(await self.redis.get(CORPUS_VERSION_KEY) or 0)
        except Exception:
            return int(time.time() // 60)  # degrade: minute-granularity versioning

    async def bump_corpus_version(self) -> int:
        try:
            return int(await self.redis.incr(CORPUS_VERSION_KEY))
        except Exception as exc:
            logger.warning("corpus version bump failed: %s", exc)
            return 0

    async def allow(self, bucket: str, limit: int, window_s: int = 60) -> bool:
        """Fixed-window rate limiter. Fails open if Redis is unavailable."""
        key = self._k("rl", f"{bucket}:{int(time.time() // window_s)}")
        try:
            pipe = self.redis.pipeline()
            pipe.incr(key)
            pipe.expire(key, window_s + 1)
            count, _ = await pipe.execute()
            return int(count) <= limit
        except Exception:
            return True

    async def ping(self) -> bool:
        try:
            return bool(await self.redis.ping())
        except Exception:
            return False
