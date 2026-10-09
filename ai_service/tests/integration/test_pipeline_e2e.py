"""End-to-end against a real Postgres+pgvector with offline (deterministic) providers."""

from __future__ import annotations

import pytest

from antix_ai.pipeline import AskRequest, ask_sync
from antix_ai.query.understanding import understand
from antix_ai.retrieval.service import retrieve

pytestmark = pytest.mark.asyncio(loop_scope="session")


async def test_index_contains_all_approved(rt, seeded):
    n = await rt.db.fetchval("SELECT count(*) FROM ai.article")
    assert n == 8
    assert await rt.db.fetchval("SELECT count(*) FROM ai.chunk") >= 8


async def test_gpt5_articles_cluster_into_one_story(rt, seeded):
    rows = await rt.db.fetch("SELECT post_id, story_id FROM ai.article WHERE post_id IN (1, 2)")
    assert len({r["story_id"] for r in rows}) == 1
    st = await rt.db.fetchrow("SELECT source_count, article_count FROM ai.story WHERE id = %s", (rows[0]["story_id"],))
    assert st["article_count"] == 2 and st["source_count"] == 2


async def test_fact_lookup_retrieves_right_article(rt, seeded):
    plan = await understand(rt, "How much did Anthropic raise from Amazon?", "How much did Anthropic raise from Amazon?", now=seeded)
    res = await retrieve(rt, plan)
    assert res.articles and res.articles[0].post_id == 3


async def test_time_window_is_enforced(rt, seeded):
    q = "what AI news was there last week"
    plan = await understand(rt, q, q, now=seeded, tz="UTC")
    assert plan.time_range is not None
    res = await retrieve(rt, plan)
    w = plan.window()
    assert all(w.start <= a.published_at < w.end for a in res.articles)


async def test_rejected_post_is_never_retrieved(rt, seeded):
    await rt.db.execute("UPDATE public.posts_post SET status = 'rejected' WHERE id = 3")
    try:
        q = "Anthropic funding Amazon"
        plan = await understand(rt, q, q, now=seeded)
        res = await retrieve(rt, plan)
        assert 3 not in {a.post_id for a in res.articles}
    finally:
        await rt.db.execute("UPDATE public.posts_post SET status = 'approved' WHERE id = 3")


async def test_ask_offline_returns_cited_extractive_answer(rt, seeded):
    out = await ask_sync(rt, AskRequest(query="What did Nvidia announce?", stream=False))
    assert out["intent"] in ("fact_lookup", "entity_overview", "latest")
    assert any(c["post_id"] == 4 for c in out["citations"]) or "[S" in out["answer"]
    assert out["trace_id"]


async def test_no_evidence_is_honest(rt, seeded):
    out = await ask_sync(rt, AskRequest(query="What did Quantum Frobnicator Corp announce yesterday?", stream=False))
    assert "couldn't find" in out["answer"].lower() or out["citations"] == [] or out["grounding"] is not None


async def test_chit_chat_needs_no_retrieval(rt, seeded):
    out = await ask_sync(rt, AskRequest(query="hello", stream=False))
    assert out["intent"] == "chit_chat" and out["citations"] == []


async def test_conversation_persists_and_bounds(rt, seeded):
    sid = "test-session-1"
    for q in ["What did Nvidia announce?", "and when does it ship?"]:
        await ask_sync(rt, AskRequest(query=q, session_id=sid, stream=False))
    n = await rt.db.fetchval("SELECT count(*) FROM ai.message WHERE conversation_id = %s", (sid,))
    assert n == 4


async def test_reingest_unchanged_is_noop(rt, seeded):
    from antix_ai.ingestion.indexer import ingest_post

    res = await ingest_post(rt, 1)
    assert res.status == "unchanged"


async def test_unapproving_removes_from_index(rt, seeded):
    from antix_ai.ingestion.indexer import ingest_post

    await rt.db.execute("UPDATE public.posts_post SET status = 'pending' WHERE id = 8")
    try:
        res = await ingest_post(rt, 8)
        assert res.status == "removed"
        assert await rt.db.fetchval("SELECT count(*) FROM ai.chunk WHERE post_id = 8") == 0
    finally:
        await rt.db.execute("UPDATE public.posts_post SET status = 'approved' WHERE id = 8")
        await ingest_post(rt, 8)


async def test_features(rt, seeded):
    from antix_ai import features

    b = await features.briefing(rt, "this week", "UTC")
    assert b["stories"]
    rel = await features.related(rt, 1, 3)
    assert rel and all(r["post_id"] != 1 for r in rel)
    assert (await features.stats(rt))["articles"] == 8
