"""Async Postgres access (psycopg 3 pool + pgvector)."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from typing import Any

import numpy as np
from pgvector.psycopg import register_vector_async
from psycopg import AsyncConnection
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

logger = logging.getLogger(__name__)


def to_async_dsn(url: str) -> str:
    """Accept SQLAlchemy-style URLs too."""
    for prefix in ("postgresql+psycopg://", "postgresql+psycopg2://", "postgres://"):
        if url.startswith(prefix):
            return "postgresql://" + url[len(prefix):]
    return url


class Database:
    def __init__(self, dsn: str, min_size: int = 1, max_size: int = 10, ef_search: int = 80):
        self._ef_search = ef_search
        self.pool = AsyncConnectionPool(
            to_async_dsn(dsn),
            min_size=min_size,
            max_size=max_size,
            open=False,
            configure=self._configure,
            kwargs={"autocommit": True, "row_factory": dict_row, "prepare_threshold": None},
            check=AsyncConnectionPool.check_connection,
        )

    async def _configure(self, conn: AsyncConnection) -> None:
        try:
            await register_vector_async(conn)
        except Exception:  # extension not installed yet (pre-migration)
            logger.warning("pgvector type not registered; run migrations")
        await conn.execute(f"SET hnsw.ef_search = {int(self._ef_search)}")
        # pgvector >=0.8: keep scanning when filters remove candidates
        try:
            await conn.execute("SET hnsw.iterative_scan = relaxed_order")
        except Exception:
            pass

    async def open(self) -> None:
        await self.pool.open(wait=True, timeout=30)

    async def close(self) -> None:
        await self.pool.close()

    @asynccontextmanager
    async def connection(self) -> AsyncIterator[AsyncConnection]:
        async with self.pool.connection() as conn:
            yield conn

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[AsyncConnection]:
        async with self.pool.connection() as conn, conn.transaction():
            yield conn

    async def fetch(self, sql: str, params: Any = None) -> list[dict[str, Any]]:
        async with self.pool.connection() as conn:
            cur = await conn.execute(sql, params)
            return await cur.fetchall()

    async def fetchrow(self, sql: str, params: Any = None) -> dict[str, Any] | None:
        async with self.pool.connection() as conn:
            cur = await conn.execute(sql, params)
            return await cur.fetchone()

    async def fetchval(self, sql: str, params: Any = None) -> Any:
        row = await self.fetchrow(sql, params)
        return next(iter(row.values())) if row else None

    async def execute(self, sql: str, params: Any = None) -> None:
        async with self.pool.connection() as conn:
            await conn.execute(sql, params)

    async def ping(self) -> bool:
        return (await self.fetchval("SELECT 1")) == 1


def vec(values: Sequence[float] | np.ndarray) -> np.ndarray:
    return np.asarray(values, dtype=np.float32)
