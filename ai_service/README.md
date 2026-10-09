# Antix News AI service

News-native question answering, briefings and story intelligence for the AI Tech News app.
Design: [architecture.md](architecture.md) · Roadmap/status: [plan.md](plan.md).

```
Django ──(post saved/approved)──► arq worker ──► ingest: clean → chunk → enrich → embed → entities → story
Django ◄──SSE──────────────────── FastAPI ──► understand → retrieve → relevance gate → context → generate → verify
                                       └──► Neon Postgres (schema "ai", pgvector + FTS) · Redis (cache, queue)
```

## Quick start (local)

```bash
cd ai_service
cp .env.example .env                  # fill in models/keys; AI_EMBED_PROVIDER=offline works with no keys
docker compose up -d db redis         # pgvector Postgres on :55432, Redis on :6381
python -m venv .venv && .venv/Scripts/pip install -e ".[dev]"     # (bin/ on macOS/Linux)
antix-ai migrate                      # creates schema "ai" (embedding dimension = AI_EMBED_DIM)
antix-ai serve --port 8100            # API
antix-ai worker                       # background indexing (separate terminal)
antix-ai backfill --days 90           # index existing approved posts
antix-ai ask "What did OpenAI announce this week?"
```

The service **reads** Django's `posts_post` / `sources_source` tables (same database) and owns schema `ai`.
Run Django's migrations first. Table names are configurable (`AI_POSTS_TABLE`, `AI_SOURCES_TABLE`).

### Wire up Django

```env
# .env of the Django app
AI_BACKEND=shadow                     # scrutinize (default) | shadow | antix
AI_SERVICE_URL=http://localhost:8100
AI_SERVICE_KEY=<same value as the service's AI_SERVICE_KEY>
```

Rollout: `shadow` (users still get Scrutinize; both answers are logged in `ai.trace`) → compare →
`antix`. Set `AI_FALLBACK_TO_SCRUTINIZE=true` during the first days of `antix` if you want a safety net.

## Embedding dimension is part of the schema

`AI_EMBED_DIM` sizes the `vector(N)` columns when you run `antix-ai migrate`. To change embedding model
or dimension later: new database/schema (or a new migration that adds columns), then `antix-ai backfill --force`.
`ai.article.embed_model` records which model produced each row.

## Models

Any OpenAI-compatible endpoint (OpenAI, vLLM, Ollama, ngrok'd local model) or Anthropic, per role:

| Role | Used for | Env prefix |
|---|---|---|
| `fast` | planning, query rewrite, enrichment, rerank, claim verification | `AI_FAST__*` |
| `strong` | final answer | `AI_STRONG__*` |
| `strong_fallback` | used if `strong` errors before the first token | `AI_STRONG_FALLBACK__*` |

`provider=offline` disables a role; every stage then has a deterministic fallback (heuristic planner,
extractive answer, rule-based checks), so the service degrades instead of failing.

## API (all `/v1/*` need header `X-Service-Key`)

| Endpoint | Purpose |
|---|---|
| `POST /v1/ask` | SSE: `status`, `token`, `final` (answer, citations, grounding, trace_id), `error` |
| `POST /v1/ask/sync` | same, one JSON response |
| `GET /v1/briefing?range=this week` | top stories, one lead article per story |
| `GET /v1/posts/{id}/related` · `/v1/stories/{id}` · `/v1/trending` | related, story timeline, trending entities |
| `POST /v1/ingest/{id}` · `/v1/ingest/reconcile` | index/remove a post; reconcile index with the app |
| `POST /v1/feedback` | 👍/👎 on a trace |
| `GET /v1/conversations/{session}` · `DELETE …` | chat history |
| `GET /v1/admin/stats` · `/admin/traces` · `POST /admin/retrieve` | ops and retrieval debugging |
| `GET /health` · `/ready` | liveness / readiness (no auth) |

## Quality: evals

```bash
antix-ai gen-evals --n 150                      # golden set from your real approved posts → evals/datasets/
antix-ai eval --backend scrutinize              # baseline of the current system (needs SCRUTINIZE_* env)
antix-ai eval --backend antix                   # the new service; same metrics, report in evals/reports/
```

Metrics: recall, citation precision, numeric faithfulness, correct refusal / hallucination on unanswerable
questions, false refusals, temporal correctness, latency. **Read and edit the generated dataset by hand**, then
add questions from 👎 traces. Every prompt or model change should come with an eval run.

## Operations

* Every request writes a row to `ai.trace` (plan, retrieved posts, answer, per-claim verdicts, latency per
  stage, token usage). Low-grounding answers: `GET /v1/admin/traces?low_grounding=true`.
* Caches are keyed by a `corpus_version` that bumps on every ingest, so a cached answer can never outlive the
  articles it was built from. Plan cache keys include `PLANNER_VERSION`; bump it when planning logic changes.
* `scripts/bench.py` measures time-to-first-token and total latency against a running instance.
* Container: `docker build -t antix-ai .`; API is the default command, `antix-ai worker` runs the worker,
  `antix-ai migrate` the migrations. Needs the Neon `vector` extension enabled (`CREATE EXTENSION vector`).

## Tests

```bash
docker compose up -d db
AI_TEST_DATABASE_URL=postgresql://postgres:antix@localhost:55432/antix_ai_test pytest -q
```

Unit tests need nothing; integration tests (marked) need pgvector Postgres and are skipped when it is
unreachable. Tests use offline providers plus a scripted fake chat model, so no API keys are needed.
