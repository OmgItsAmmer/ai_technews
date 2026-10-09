"""Alembic environment. Owns only the ``ai`` schema; never touches Django tables."""

from __future__ import annotations

from alembic import context
from sqlalchemy import create_engine, text

from antix_ai.config import get_settings


def _sync_url(url: str) -> str:
    for prefix in ("postgresql://", "postgres://", "postgresql+psycopg2://"):
        if url.startswith(prefix):
            return "postgresql+psycopg://" + url[len(prefix):]
    return url


def run_migrations_online() -> None:
    engine = create_engine(_sync_url(get_settings().database_url), pool_pre_ping=True)
    with engine.connect() as conn:
        conn.execute(text("CREATE SCHEMA IF NOT EXISTS ai"))
        conn.commit()
        context.configure(
            connection=conn,
            version_table="alembic_version",
            version_table_schema="ai",
            include_schemas=True,
            transaction_per_migration=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    raise SystemExit("offline migrations are not supported; run against a database")
run_migrations_online()
