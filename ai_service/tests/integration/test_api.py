from __future__ import annotations

import httpx
import pytest

from antix_ai.api.app import create_app

pytestmark = pytest.mark.asyncio(loop_scope="session")
KEY = {"X-Service-Key": "test-service-key-test-service-key"}


@pytest.fixture
async def client(rt, seeded):
    app = create_app(runtime=rt)
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
            yield c


async def test_health_open_and_ready(client):
    assert (await client.get("/health")).status_code == 200
    r = await client.get("/ready")
    assert r.json()["database"] is True


async def test_auth_required(client):
    assert (await client.post("/v1/ask/sync", json={"query": "hi"})).status_code == 401
    assert (await client.post("/v1/ask/sync", json={"query": "hi"}, headers={"X-Service-Key": "bad"})).status_code == 401


async def test_ask_sync_and_validation(client):
    r = await client.post("/v1/ask/sync", json={"query": "What did Meta release?"}, headers=KEY)
    assert r.status_code == 200 and r.json()["trace_id"]
    assert (await client.post("/v1/ask/sync", json={"query": ""}, headers=KEY)).status_code == 422


async def test_ask_streams_sse(client):
    async with client.stream("POST", "/v1/ask", json={"query": "what did Meta release?"}, headers=KEY) as r:
        assert r.headers["content-type"].startswith("text/event-stream")
        body = "".join([chunk async for chunk in r.aiter_text()])
    assert "event: final" in body and body.rstrip().endswith("data: {}")


async def test_feedback_and_traces(client):
    r = await client.post("/v1/ask/sync", json={"query": "hello"}, headers=KEY)
    tid = r.json()["trace_id"]
    assert (await client.post("/v1/feedback", json={"trace_id": tid, "rating": -1, "note": "meh"}, headers=KEY)).json()["ok"]
    t = await client.get(f"/v1/admin/traces/{tid}", headers=KEY)
    assert t.status_code == 200 and t.json()["feedback"] == -1
    bad = await client.get("/v1/admin/traces?negative_feedback=true", headers=KEY)
    assert any(x["id"] == tid for x in bad.json()["traces"])


async def test_content_endpoints(client):
    assert (await client.get("/v1/briefing?range=this week", headers=KEY)).json()["stories"]
    assert (await client.get("/v1/posts/1/related", headers=KEY)).json()["related"]
    assert (await client.get("/v1/trending", headers=KEY)).status_code == 200
    assert (await client.get("/v1/stories/999999", headers=KEY)).status_code == 404
    s = (await client.get("/v1/admin/stats", headers=KEY)).json()
    assert s["articles"] == 8
    d = (await client.post("/v1/admin/retrieve", json={"query": "Nvidia Blackwell"}, headers=KEY)).json()
    assert d["articles"][0]["post_id"] == 4


async def test_ingest_inline_and_reconcile_route_precedence(client):
    r = await client.post("/v1/ingest/1?wait=true", headers=KEY)
    assert r.json()["status"] in ("unchanged", "indexed")
    # must route to reconcile (503 without a queue), not 422 from /ingest/{post_id}
    rr = await client.post("/v1/ingest/reconcile", json={}, headers=KEY)
    assert rr.status_code in (200, 503)


async def test_conversation_history_and_delete(client):
    await client.post("/v1/ask/sync", json={"query": "What did Meta release?", "session_id": "api-s1"}, headers=KEY)
    h = (await client.get("/v1/conversations/api-s1", headers=KEY)).json()
    assert [m["role"] for m in h["messages"]] == ["user", "assistant"]
    await client.delete("/v1/conversations/api-s1", headers=KEY)
    assert (await client.get("/v1/conversations/api-s1", headers=KEY)).json()["messages"] == []


async def test_shadow_records_legacy_answer(client, rt):
    r = await client.post("/v1/shadow", json={"query": "q", "answer": "legacy answer", "cited_post_ids": [1, 2],
                                              "latency_ms": 1234.5}, headers=KEY)
    assert r.json()["ok"]
    row = await rt.db.fetchrow("SELECT backend, kind FROM ai.trace WHERE answer = 'legacy answer'")
    assert row == {"backend": "scrutinize", "kind": "shadow"}
