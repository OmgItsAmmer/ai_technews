"""Entity canonicalization and linking (articles at ingest, mentions at query time)."""

from __future__ import annotations

import re
from datetime import datetime

from psycopg import AsyncConnection

from antix_ai.core.db import Database
from antix_ai.ingestion.enricher import EntityMention

_SUFFIX = re.compile(r"\b(inc|corp|corporation|ltd|llc|plc|co|gmbh|ag|sa|limited)\.?$", re.I)
_PUNCT = re.compile(r"[^\w\s.+#-]")


def normalize_entity(name: str) -> str:
    n = _PUNCT.sub("", name.lower()).strip()
    n = re.sub(r"^the\s+", "", n)
    n = _SUFFIX.sub("", n).strip(" .,-")
    n = re.sub(r"[\s_]+", " ", n)
    return n.strip()


async def link_entities(
    conn: AsyncConnection,
    post_id: int,
    mentions: list[EntityMention],
    seen_at: datetime | None,
) -> list[int]:
    """Upsert entities and article links. Returns linked entity ids (most salient first)."""
    await conn.execute("DELETE FROM ai.article_entity WHERE post_id = %s", (post_id,))
    linked: dict[int, float] = {}
    for m in mentions:
        norm = normalize_entity(m.name)
        if len(norm) < 2:
            continue
        cur = await conn.execute(
            """
            SELECT id FROM ai.entity
            WHERE norm_name = %(n)s OR %(n)s = ANY(aliases)
            ORDER BY (norm_name = %(n)s) DESC, mention_count DESC
            LIMIT 1
            """,
            {"n": norm},
        )
        row = await cur.fetchone()
        if row is None and len(norm) >= 5:
            # near-duplicate spelling ("open ai" vs "openai"): trigram match, same type
            cur = await conn.execute(
                """
                SELECT id FROM ai.entity
                WHERE norm_name %% %(n)s AND similarity(norm_name, %(n)s) >= 0.8
                  AND (type = %(t)s OR type = 'other' OR %(t)s = 'other')
                ORDER BY similarity(norm_name, %(n)s) DESC LIMIT 1
                """,
                {"n": norm, "t": m.type},
            )
            row = await cur.fetchone()
            if row:
                await conn.execute(
                    "UPDATE ai.entity SET aliases = array_append(aliases, %s) "
                    "WHERE id = %s AND NOT (%s = ANY(aliases))",
                    (norm, row["id"], norm),
                )
        if row is None:
            cur = await conn.execute(
                """
                INSERT INTO ai.entity (name, norm_name, type, first_seen, last_seen)
                VALUES (%s, %s, %s, COALESCE(%s, now()), COALESCE(%s, now()))
                ON CONFLICT (norm_name) DO UPDATE SET norm_name = EXCLUDED.norm_name
                RETURNING id
                """,
                (m.name.strip(), norm, m.type, seen_at, seen_at),
            )
            row = await cur.fetchone()
        eid = row["id"]
        linked[eid] = max(linked.get(eid, 0.0), m.salience)

    for eid, sal in linked.items():
        await conn.execute(
            "INSERT INTO ai.article_entity (post_id, entity_id, salience) VALUES (%s, %s, %s)",
            (post_id, eid, sal),
        )
    if linked:
        await conn.execute(
            """
            UPDATE ai.entity e SET
                mention_count = (SELECT count(*) FROM ai.article_entity ae WHERE ae.entity_id = e.id),
                last_seen = GREATEST(e.last_seen, COALESCE(%s, now()))
            WHERE e.id = ANY(%s)
            """,
            (seen_at, list(linked)),
        )
        # upgrade generic types once a model tells us what the entity is
        for m in mentions:
            if m.type != "other":
                await conn.execute(
                    "UPDATE ai.entity SET type = %s WHERE norm_name = %s AND type = 'other'",
                    (m.type, normalize_entity(m.name)),
                )
    return [eid for eid, _ in sorted(linked.items(), key=lambda kv: -kv[1])]


async def resolve_query_entities(db: Database, text: str, hints: list[str]) -> list[dict]:
    """Find known entities mentioned in a query (exact names/aliases over word n-grams + hints)."""
    words = re.findall(r"[\w.+#-]+", text.lower())
    grams = {normalize_entity(g) for g in hints}
    for n in (1, 2, 3):
        for i in range(len(words) - n + 1):
            grams.add(normalize_entity(" ".join(words[i : i + n])))
    grams = {g for g in grams if len(g) >= 2}
    if not grams:
        return []
    return await db.fetch(
        """
        SELECT id, name, norm_name, type, mention_count FROM ai.entity
        WHERE norm_name = ANY(%(g)s) OR aliases && %(g)s
        ORDER BY length(norm_name) DESC, mention_count DESC
        LIMIT 8
        """,
        {"g": list(grams)},
    )
