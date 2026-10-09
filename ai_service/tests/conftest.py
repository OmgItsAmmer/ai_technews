"""Shared fixtures.

Unit tests need nothing. Integration tests need pgvector Postgres at AI_TEST_DATABASE_URL, e.g.
  docker run -d -p 55432:5432 -e POSTGRES_PASSWORD=antix -e POSTGRES_DB=antix_ai_test pgvector/pgvector:pg16
  AI_TEST_DATABASE_URL=postgresql://postgres:antix@localhost:55432/antix_ai_test
Redis is optional: without it caches/rate limits degrade gracefully (fakeredis-like stub).
"""

from __future__ import annotations

import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

import psycopg
import pytest
import pytest_asyncio

TEST_DSN = os.environ.get("AI_TEST_DATABASE_URL", "postgresql://postgres:antix@localhost:55432/antix_ai_test")
EMBED_DIM = 256
ROOT = Path(__file__).resolve().parent.parent

# Test environment before any antix_ai import reads settings
os.environ.setdefault("AI_DATABASE_URL", TEST_DSN)
os.environ.setdefault("AI_SERVICE_KEY", "test-service-key-test-service-key")
os.environ.setdefault("AI_ENV", "test")
os.environ.setdefault("AI_EMBED_PROVIDER", "offline")
os.environ.setdefault("AI_EMBED_DIM", str(EMBED_DIM))
os.environ.setdefault("AI_FAST__PROVIDER", "offline")
os.environ.setdefault("AI_STRONG__PROVIDER", "offline")
os.environ.setdefault("AI_RERANK", "none")
os.environ.setdefault("AI_REDIS_URL", "redis://localhost:6379/9")
os.environ.setdefault("AI_LOG_JSON", "false")

from antix_ai.config import Settings  # noqa: E402


def _db_available() -> bool:
    try:
        with psycopg.connect(TEST_DSN, connect_timeout=2):
            return True
    except Exception:
        return False


DB_UP = _db_available()
needs_db = pytest.mark.skipif(not DB_UP, reason="test Postgres not reachable (AI_TEST_DATABASE_URL)")


def pytest_collection_modifyitems(items):
    for item in items:
        if "integration" in str(item.fspath):
            item.add_marker(pytest.mark.integration)
            item.add_marker(needs_db)


@pytest.fixture(scope="session")
def settings() -> Settings:
    from antix_ai.config import get_settings

    get_settings.cache_clear()
    return get_settings()


@pytest.fixture(scope="session")
def migrated_db():
    """Fresh ai schema + stand-in Django tables."""
    if not DB_UP:
        pytest.skip("no test database")
    with psycopg.connect(TEST_DSN, autocommit=True) as c:
        c.execute("DROP SCHEMA IF EXISTS ai CASCADE")
        c.execute("DROP TABLE IF EXISTS public.posts_post, public.sources_source CASCADE")
        c.execute(
            """
            CREATE TABLE public.sources_source (
                id bigserial PRIMARY KEY, name text NOT NULL, homepage_url text DEFAULT '',
                rss_url text, source_type text NOT NULL DEFAULT 'media', badge_label text DEFAULT '',
                is_active boolean NOT NULL DEFAULT true
            );
            CREATE TABLE public.posts_post (
                id bigserial PRIMARY KEY, source_id bigint REFERENCES public.sources_source(id),
                title text NOT NULL, original_url text UNIQUE, author text,
                published_at timestamptz, fetched_at timestamptz NOT NULL DEFAULT now(),
                raw_content text NOT NULL DEFAULT '', summary text NOT NULL DEFAULT '',
                tags jsonb NOT NULL DEFAULT '[]', status text NOT NULL DEFAULT 'pending'
            );
            """
        )
    env = {**os.environ, "AI_DATABASE_URL": TEST_DSN, "AI_EMBED_DIM": str(EMBED_DIM)}
    r = subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=ROOT, env=env,
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return TEST_DSN


class StubRedis:
    """Tiny in-memory Redis subset so tests don't need a server."""

    def __init__(self):
        self.d: dict[str, str] = {}

    async def get(self, k):
        return self.d.get(k)

    async def set(self, k, v, ex=None):
        self.d[k] = v

    async def incr(self, k):
        self.d[k] = str(int(self.d.get(k, 0)) + 1)
        return int(self.d[k])

    async def delete(self, *ks):
        for k in ks:
            self.d.pop(k, None)

    async def ping(self):
        return True

    async def aclose(self):
        pass

    def pipeline(self):
        outer = self

        class P:
            def __init__(self):
                self.ops = []

            def incr(self, k):
                self.ops.append(("incr", k))

            def expire(self, k, s):
                self.ops.append(("expire", k))

            async def execute(self):
                res = []
                for op, k in self.ops:
                    res.append(await outer.incr(k) if op == "incr" else True)
                return res

        return P()


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def rt(migrated_db, settings):
    from antix_ai.core.cache import Cache
    from antix_ai.core.db import Database
    from antix_ai.providers.registry import build_providers
    from antix_ai.runtime import Runtime

    db = Database(TEST_DSN, 1, 5)
    await db.open()
    runtime = Runtime(settings=settings, db=db, cache=Cache(StubRedis()), providers=build_providers(settings))
    yield runtime
    await db.close()


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def seeded(rt):
    """Insert the corpus into the stand-in Django tables and index it."""
    from antix_ai.ingestion.indexer import reconcile
    from tests.corpus import SOURCES, articles

    now = datetime.now(UTC)
    for sid, name, stype in SOURCES:
        await rt.db.execute(
            "INSERT INTO public.sources_source (id, name, source_type) VALUES (%s, %s, %s) "
            "ON CONFLICT (id) DO NOTHING", (sid, name, stype))
    import json

    for a in articles(now):
        await rt.db.execute(
            """INSERT INTO public.posts_post (id, source_id, title, original_url, published_at,
               raw_content, summary, tags, status) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,'approved')
               ON CONFLICT (id) DO NOTHING""",
            (a["id"], a["source"], a["title"], f"https://example.com/{a['id']}", a["at"], a["body"],
             "", json.dumps(a["tags"])))
    report = await reconcile(rt, days=365, force=True)
    assert report.failed == 0, report.errors
    return now
