# Antix News AI Service — Implementation Plan & Status

Companion to [architecture.md](architecture.md). Status legend: ✅ built and tested · 🟡 built, but not
verifiable without things only you have (API keys, production data, a running Scrutinize) · ⬜ not done.

**Migration rule (unchanged):** Scrutinize stays the default until the new service beats it on the eval suite
and passes shadow mode. Nothing here switches production by itself: `AI_BACKEND` defaults to `scrutinize`.

## What the numbers do and don't prove

Everything below was tested with the **offline providers** (deterministic hashing embedder, extractive answers)
plus a **scripted fake LLM** on an 8-article seed corpus. That proves the pipeline, filters, gates, verification,
persistence, API and Django wiring behave. It does **not** measure real answer quality, real embedding recall,
or real LLM latency. Those need a run with your models on your corpus (Phase 0 / 6 below).

Current test status: service 77 passed (`ruff` clean) · Django `apps/ai` 17 passed · full Django suite 70 passed,
3 failed (pre-existing live-network/LLM tests, unrelated).

---

## Phase 0 — Foundation & baseline

- ✅ Scaffold `ai_service/` (FastAPI, pydantic-settings, psycopg3 pool, Alembic, pytest, ruff, CLI).
- ✅ `config.py` with no secret defaults; service key required.
- ✅ pgvector schema `ai` (migration `0001`; verified upgrade → downgrade → upgrade).
- ✅ Provider layer: OpenAI-compatible, Anthropic, offline; fast/strong/fallback roles; retries; token accounting;
  `<think>` stripping (streaming-safe); robust JSON extraction with corrective retry.
- ✅ `ai.trace` + per-stage timings and token usage.
- ✅ Eval harness: metrics, golden-set generator from the real corpus, runner, backends for this service **and
  Scrutinize** (`/v2/search`, same Django contract), reports + `ai.eval_run` history.
- 🟡 **Baseline against Scrutinize not run** — needs your running Scrutinize and `SCRUTINIZE_*` keys.
  Run `antix-ai gen-evals`, review the file, then `antix-ai eval --backend scrutinize`.
- ✅ Removed hardcoded Scrutinize keys from `apps/frontend/scrutinize.py`, `config/settings/base.py` and two docs.
- ⬜ **Rotate the leaked Scrutinize keys** — they remain in git history. (Yours to do.)

## Phase 1 — Ingestion & indexing

- ✅ `article`, `chunk` (HNSW + GIN tsvector), denormalized filter columns.
- ✅ Cleaner, structure-aware chunker (paragraph/sentence, overlap, abbreviation-safe).
- ✅ Enricher (summary, key facts, entities, event signature, type, importance) with heuristic fallback.
- ✅ Contextual chunk prefixes; content-hash skip (re-ingest unchanged = no model calls — tested).
- ✅ Idempotent `ingest`, `reconcile`, `backfill`; removal on reject/delete (tested).
- ✅ Django hook: post_save/post_delete → Celery task → service (retries; broker outage can't break saving a post).
- ➖ Deviation: no `Post.updated_at` migration. Reconcile compares a content hash instead, which also catches
  tag/source/URL edits and needs no change to the Django schema.
- 🟡 Backfill of the last 90 days not run against your Neon database (`antix-ai backfill`). Cost depends on
  corpus size and your fast model; unchanged posts are skipped on re-runs.

## Phase 2 — Query understanding & hybrid retrieval

- ✅ Deterministic time parser (today/yesterday/this week/since Monday/Oct 5/September/past N days/…, user timezone, 16 cases).
- ✅ Query planner (LLM structured output + heuristic fallback; the LLM never computes dates); plan cache.
- ✅ Hybrid pgvector + FTS in one SQL round trip with metadata filters; RRF; recency half-life per intent;
  entity/importance/corroboration priors; article-level path for latest/briefing.
- ✅ Rerank: LLM listwise or HTTP cross-encoder (TEI/Cohere/Jina). ➖ No local cross-encoder is bundled.
- ✅ Diversification (≤2 chunks/article, ≤2 articles/story; 1 for latest/briefing).
- ✅ `POST /v1/admin/retrieve` debug endpoint.
- ➕ **Added: relevance gate** (`retrieval/relevance.py`). Found by the eval harness: nearest-neighbour search always
  returns something, so an invented company still got loosely related articles presented as evidence. Now a question
  naming entities that no candidate mentions returns *no evidence* and the assistant says so.
- 🟡 Retrieval recall and the "+20 pts over baseline" target are unmeasured on real data.

## Phase 3 — Context builder & grounded generation

- ✅ Token-budgeted, article-grouped evidence with `[S#]` ids, source/date/story headers, "reported by N outlets",
  coverage notes (window, counts, thin/single-source, entities with no coverage), edge-of-context ordering.
- ✅ Versioned prompts (`prompts/*.vN.md`) with the grounding contract; streaming generator with fallback to a
  secondary model before the first token; partial-answer handling.
- ✅ Citation payload carries `post_id`, title, source, url, date, timestamp (no filename regex).
- ✅ Honest "no evidence" replies; scoped replies for chit-chat / out-of-scope.
- 🟡 Targets (citation precision ≥95%, faithfulness ≥90%, refusal ≥90%) need a real-model eval run.

## Phase 4 — Verification

- ✅ Unknown `[S#]` stripped; uncited-claim detection; number support against cited sources; temporal check;
  optional LLM claim-support check on the fast model; unsupported sentences removed; `grounding` score on every answer.
- ✅ Calendar dates are validated by the temporal check, not the number check (a regression test covers a
  model writing "October 8, 2026" when the article body doesn't contain the date).
- 🟡 LLM claim-support quality unmeasured (scripted-model tests only).

## Phase 5 — Conversation & memory

- ✅ Redis hot state + Postgres `conversation`/`message`; follow-up → standalone rewrite (skipped when unnecessary);
  rolling summary of old turns; focus entities carried forward; survives restarts; per-session rate limit.
- ✅ Replaces the in-memory `_CHAT_SESSIONS` dict when `AI_BACKEND=antix`.

## Phase 6 — Django integration & shadow mode

- ✅ `apps/ai/client.py`, `AI_BACKEND = scrutinize | shadow | antix`, optional fallback to Scrutinize.
- ✅ Shadow mode: serve Scrutinize, run the new service in the background on an isolated session, store Scrutinize's
  answer in `ai.trace` (`backend='scrutinize'`) next to the new one for comparison.
- ✅ Ask-AI UI: SSE streaming with automatic fallback to the JSON endpoint, final re-render with citation cards,
  👍/👎 feedback → `ai.trace.feedback`. 🟡 **Frontend not exercised in a browser** (JS syntax-checked only).
- ✅ Fetch pipeline skips the Scrutinize upload when `AI_BACKEND=antix`.
- ✅ Dockerfile built and booted (migrate → healthy → ready), compose file, CI workflow, Makefile targets.
- ⬜ Fly.io/production deployment config and secrets (needs your environment).
- ⬜ ≥1 week of shadow traffic and human review before flipping to `antix`.

## Phase 7 — Performance

- ✅ Caches: query embedding, plan (versioned), answers for latest/briefing keyed by `corpus_version`.
- ✅ Parallel sub-query embedding and retrieval; connection pool; HNSW iterative scan for filtered queries.
- ✅ `scripts/bench.py` (TTFT/total p50/p95 vs the architecture targets). Offline run, 40 requests at concurrency 8:
  0 errors, TTFT p50 ≈ 42 ms — this is retrieval-path overhead only; real LLM latency is not included.
- ⬜ HNSW `ef_search` tuning on the real corpus, partial indexes, 10× load test.

## Phase 8 — News intelligence

- ✅ Story clustering at ingest (similarity + entity-overlap tiers; GPT-5 two-outlet case tested).
- ✅ `GET /v1/briefing`, `/v1/stories/{id}`, `/v1/posts/{id}/related`, `/v1/trending` (API only).
- ⬜ Admin merge/split for stories; entity pages and UI for briefing/related; KeywordSetting-aware "my topics";
  per-source credibility weights in ranking.

## Phase 9 — Decommission Scrutinize dependency

- ⬜ Intentionally not started. Only after shadow parity: remove `ScrutinizeClient`, `sync_scrutinize`,
  `Post.scrutinize_file_id`, env vars, and the `Scrutinize` submodule pointer.

---

## Next steps for you (in order)

1. Rotate the Scrutinize keys that were hardcoded in the repo.
2. Enable `vector` on Neon, fill `ai_service/.env`, `antix-ai migrate`, `antix-ai worker`, `antix-ai backfill`.
3. `antix-ai gen-evals`, review/edit the set, run the **Scrutinize baseline**, then the new service. Iterate on prompts
   and thresholds (`story_similarity`, `SEMANTIC_FLOOR`, budgets) using the reports.
4. `AI_BACKEND=shadow`, compare in `ai.trace`; then `antix`.
