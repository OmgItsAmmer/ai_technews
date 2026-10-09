# Antix News AI Service — Architecture

A purpose-built AI layer for the AI Tech News app. It replaces the app's dependency on
Scrutinize (a general-purpose RAG platform) with a service that understands **news**:
time, sources, stories, entities, and editorial status.

---

## 1. Why a dedicated service

Scrutinize is document-centric and domain-agnostic. For news that causes concrete,
architectural failure modes — not prompt problems:

| # | Problem in current setup | Evidence in code | Effect |
|---|---|---|---|
| 1 | Articles are flattened into `post_{id}.txt` and uploaded as files | `apps/frontend/scrutinize.py` `upload_post()` | Date, source, tags, status become plain text inside chunks — not filterable |
| 2 | Retrieval only supports `modality_filter` | `Scrutinize/.../v2/pipeline_orchestrator.py` | "Latest news", "this week", "from TechCrunch" are answered by semantic similarity, not by facts |
| 3 | No notion of "now" | no current-date injection in the pipeline | Model guesses recency → stale or invented timelines |
| 4 | Second copy of data in Qdrant, kept in sync by a Celery job | `apps/posts/services/sync_scrutinize.py` | Drift: deleted/rejected/edited posts can still be retrieved |
| 5 | Citations are reverse-mapped by filename regex after generation | `apps/frontend/chat.py` | Answer text is not bound to evidence; claims can be uncited or mis-cited |
| 6 | Same story from 5 sources = 5 near-duplicate chunks | no story clustering | Context window wasted on duplicates, real diversity lost |
| 7 | Generic web-search tool can enter the context | `mcp_manager.py` | Unvetted content mixed with curated articles |
| 8 | Chat history kept in process memory | `_CHAT_SESSIONS` dict in `chat.py` | Lost on restart, broken with multiple workers |

**Design principle:** hallucinations are prevented by *structure* (what evidence reaches the
model, how it's labeled, how answers are checked), with prompts as the last line of defence,
not the first.

---

## 2. Goals & non-goals

**Goals**
- Grounded answers: every factual claim about news is cited to an article in our DB.
- Time-correct: "today / this week / latest" resolve against the real clock and `published_at`.
- Honest: when evidence is missing, say so instead of guessing.
- Fast: first token < 1.5 s p50, full answer < 6 s p95 (see §10).
- App-aware: uses Sources, Tags, KeywordSettings, post status, and story clusters.
- Measurable: every change is gated by an eval suite.

**Non-goals**
- Generic document Q&A, PDF/video ingestion, multi-tenant projects (that stays in Scrutinize).
- Agentic tool-use with open web access in the default path (optional, isolated, later).

---

## 3. System overview

```
                         ┌──────────────────────────── Django app (existing) ──────────────────────────┐
                         │  fetcher (Celery) → Post(status=pending) → admin approves → Post(approved)  │
                         │                              │ post_saved / approved signal                 │
                         │                              ▼                                              │
                         │                    ai_service.client.enqueue_ingest(post_id)                │
                         │  Ask AI view ──────────────► ai_service.client.ask(...)  (SSE stream)       │
                         └──────────────────────────────┬──────────────────────────────────────────────┘
                                                        │ HTTP (internal, service key)
┌───────────────────────────────────── ai_service (FastAPI + worker) ─────────────────────────────────────┐
│                                                                                                         │
│  INGESTION (worker)                         QUERY (API)                                                 │
│  ┌─────────────┐                            ┌───────────────┐   ┌──────────────┐   ┌────────────────┐   │
│  │ load Post   │                            │ 1 Conversation│──►│ 2 Query      │──►│ 3 Retrieval    │   │
│  │ clean text  │                            │   resolver    │   │   understand │   │   planner      │   │
│  │ chunk       │                            └───────────────┘   └──────────────┘   └───────┬────────┘   │
│  │ enrich (LLM)│                                                                           ▼            │
│  │ embed       │                            ┌───────────────┐   ┌──────────────┐   ┌────────────────┐   │
│  │ cluster     │                            │ 6 Verifier    │◄──│ 5 Grounded   │◄──│ 4 Context      │   │
│  │ upsert      │                            │   & citations │   │   generator  │   │   builder      │   │
│  └──────┬──────┘                            └───────┬───────┘   └──────────────┘   └────────────────┘   │
│         │                                           ▼                                                   │
│         │                                     stream to client + trace log                              │
└─────────┼───────────────────────────────────────────────────────────────────────────────────────────────┘
          ▼
   Neon PostgreSQL  (single source of truth)
   ├─ public.posts_post, sources_source … (owned by Django, read-only for ai_service)
   └─ schema "ai": article_index, chunk, entity, article_entity, story, conversation, trace, eval_*
      + pgvector (HNSW) + tsvector (GIN)
   Redis: cache, rate limits, session hot state, job queue
```

### Key decision: same Postgres, separate schema, no separate vector DB
- pgvector on Neon gives vector search **joined with real metadata** in one SQL query
  (`WHERE status='approved' AND published_at >= now()-'7 days' AND source_id IN (…)`).
- Removes the sync job and drift problem entirely; deleting/rejecting a post is a
  `ON DELETE CASCADE` / status check, not a cross-system sync.
- Corpus size (thousands → low millions of chunks) is well within pgvector + HNSW limits.
- `ai_service` owns the `ai` schema and its migrations (Alembic); it only **reads** Django tables.

### Key decision: separate deployable service, in this repo
- Lives at `ai_service/` as its own Python package, own `Dockerfile`, own Fly app/process.
- Django talks to it through a thin typed client (`apps/ai/client.py`), replacing `ScrutinizeClient`.
- Lets AI deps (embeddings, rerankers, async I/O) evolve without touching the Django runtime,
  while shared DB keeps data consistent.

---

## 4. Data model (`ai` schema)

```
article_index            one row per indexed Post
  post_id (PK, FK → posts_post.id, ON DELETE CASCADE)
  content_hash            -- re-index only when content changes
  title, source_id, source_name, author, url
  published_at, status    -- denormalized for filtering; refreshed on change
  tags text[]
  summary_short           -- 1–2 sentence LLM summary (for briefings)
  key_facts jsonb         -- [{fact, numbers, entities}] extracted at ingest
  story_id (FK → story)
  language, quality_score, indexed_at, embed_model

chunk
  id, post_id (FK), ord
  text, token_count
  heading_path            -- e.g. "Title > Section"
  contextual_prefix       -- "From <source>, <date>: <article gist>" (contextual retrieval)
  embedding vector(N)     -- HNSW index (cosine)
  tsv tsvector            -- GIN index; weighted: title A, prefix B, body C
  published_at, source_id, status, tags  -- denormalized for filtered ANN

entity                    canonical companies / products / models / people / orgs
  id, name, type, aliases text[], embedding

article_entity (post_id, entity_id, salience)

story                     cluster of articles covering the same event
  id, headline, first_seen, last_updated, article_count, centroid vector(N)

conversation / message    durable chat state (Redis holds hot copy)
  focus_entities, focus_story_ids, rolling_summary

trace                     one row per query: plan, retrieved ids, prompt tokens, latency, verdicts
eval_case / eval_run      golden questions + results
```

---

## 5. Ingestion pipeline

Triggered when a post becomes `approved` (signal → enqueue), on edit (content hash change),
and by a nightly reconcile job (catches anything missed). Idempotent per `post_id`.

1. **Load & clean** — strip boilerplate, normalize whitespace/unicode, detect language.
2. **Chunk** — structure-aware (paragraph/heading boundaries), ~350–500 tokens, ~15% overlap.
   Short articles (< 600 tokens) = single chunk.
3. **Enrich (fast LLM, structured output)** — one call per article:
   `summary_short`, `key_facts[]` (with exact numbers/dates/quotes), `entities[]` (name, type),
   `event_signature` (who did what), quality flags (press release, opinion, rumor).
4. **Contextual prefix** — prepend a 1-line situating context to each chunk before embedding
   (source, date, article gist). Large, proven gain for retrieval on short news chunks.
5. **Embed** — batch, cached by `content_hash`; model recorded per row for safe migrations.
6. **Entity linking** — match to canonical `entity` via alias table + embedding similarity.
7. **Story clustering** — assign to an existing story if (entity overlap ∧ embedding sim ≥ τ ∧
   within 72 h), else create a new story. Updates `story.last_updated`.
8. **Upsert** in one transaction.

Removal: post rejected/deleted → chunks excluded instantly by `status` filter / FK cascade.

---

## 6. Query pipeline

### 6.1 Conversation resolver
- Loads session (Redis → Postgres fallback): last N turns + `rolling_summary` + focus entities/stories.
- Rewrites follow-ups into a **standalone query** ("what about their pricing?" →
  "What is OpenAI's pricing for GPT-x announced on <date>?") using a fast model.
- Old turns are compressed into `rolling_summary`; raw history never grows unbounded.

### 6.2 Query understanding (fast model, structured output, ~200 ms)
Produces a `QueryPlan`:
```json
{
  "intent": "latest | briefing | fact_lookup | entity_overview | compare | timeline | explain_concept | opinion_analysis | out_of_scope | chit_chat",
  "standalone_query": "...",
  "time_range": {"from": "2026-10-02", "to": "2026-10-09", "source": "explicit|implied|default"},
  "entities": ["OpenAI", "Anthropic"],
  "sources": ["TechCrunch"],
  "tags": ["LLM"],
  "sub_queries": ["..."],          // for compare / multi-part questions
  "answer_shape": "bullets | paragraph | table | timeline",
  "needs_freshness": true
}
```
Time phrases are resolved **in code** (dateparser + the user's timezone + `now()`), not by the LLM.

### 6.3 Retrieval planner (intent → strategy)

| Intent | Strategy |
|---|---|
| `latest`, `briefing` | **SQL-first**: approved posts in time range, ranked by recency × importance, one per story; uses `summary_short` |
| `fact_lookup` | Hybrid search (vector + BM25) with metadata filters → rerank |
| `entity_overview` | Entity → linked articles in range → top stories → chunks |
| `compare` | Run sub-queries in parallel, balance evidence per side |
| `timeline` | Entity/story articles ordered by `published_at`, key_facts as events |
| `explain_concept` | Hybrid search; model may use general knowledge **labeled as background**, news claims still cited |
| `out_of_scope` / `chit_chat` | No retrieval; short scoped reply |

**Hybrid search** (single SQL round-trip per sub-query):
- pgvector ANN top-50 + Postgres FTS top-50, both under the same filters.
- Fuse with Reciprocal Rank Fusion, apply recency decay (half-life tuned per intent).
- **Rerank** top-40 → top-12 with a cross-encoder (local `bge-reranker` class or API reranker).
- **Diversify**: max 2 chunks per article, max 3 articles per story (MMR).

### 6.4 Context builder (the core of "best context management")
- **Token budget** per intent (e.g. 6k evidence tokens default), never "stuff everything".
- Evidence is grouped **by article**, each with a stable short ID and a metadata header:
  ```
  [S3] TechCrunch · 2026-10-08 · "Anthropic releases …" · story #412 (4 sources)
  <relevant passages only, in original order>
  key facts: …
  ```
- Includes `TODAY = 2026-10-09 (user tz)` and the resolved time window explicitly.
- Adds *coverage notes*: "No articles found for 2026-10-01..10-03", "Only 1 source reports this".
- Ordering: most relevant at start and end (mitigates lost-in-the-middle).
- Conversation focus is included as a compact block, not raw transcript.

### 6.5 Grounded generator (strong model, streaming)
- System contract: answer **only** from evidence for news claims; every sentence carrying a
  fact ends with `[S#]`; when evidence is insufficient, say what's missing; never invent
  dates, numbers, quotes, or sources; distinguish *reported* vs *confirmed* vs *rumor*.
- Output is streamed as text with inline citation markers; a structured trailer lists
  used source IDs.
- Prompts are versioned files (`prompts/<intent>.v3.md`) tied to eval runs.

### 6.6 Verifier (post-generation, runs on the stream tail)
1. **Citation integrity** (code): every `[S#]` exists in context; strip/flag unknown ones.
2. **Uncited-claim detection** (code + heuristics): sentences with numbers/dates/names lacking a citation.
3. **Claim support check** (fast model / NLI, only for flagged or high-risk answers):
   does `[S#]` actually support the sentence? Unsupported → remove or regenerate once.
4. **Temporal check**: dates mentioned in the answer fall within cited articles' dates.
5. Final answer carries a `grounding` score; low scores are logged and surfaced in admin.

Citations returned to Django already contain `post_id`, title, source, url, date — no regex mapping.

---

## 7. App-environment awareness

The service is "smarter than Scrutinize" because it uses what only this app knows:
- **Editorial status**: only `approved` posts are ever retrievable.
- **Sources**: source credibility weight (configurable per `Source`) feeds ranking; users can ask "from X".
- **Tags & KeywordSetting**: boost tracked keywords; power "what's new in my topics".
- **Stories**: multi-source corroboration ("reported by 4 outlets") and dedup.
- **Recency & clock**: everything time-relative is computed, not guessed.
- **Corpus stats**: the model is told how many articles exist in the window, so it can say
  "only 2 articles this week mention X" instead of overgeneralizing.

Additional endpoints this enables: daily/weekly briefing, story timelines, entity pages,
"related articles" for a post, trend detection (entity mention velocity).

---

## 8. API surface

```
POST /v1/ask                 {query, session_id, user_tz, filters?}  → SSE: tokens, citations, done
POST /v1/ask/sync            same, non-streaming (tests, admin)
GET  /v1/briefing?range=day  → structured briefing grouped by story
GET  /v1/posts/{id}/related  → related articles
GET  /v1/stories/{id}        → story + timeline
POST /v1/ingest/{post_id}    → enqueue (idempotent)
POST /v1/ingest/reconcile    → admin backfill/reconcile
GET  /v1/health, /v1/ready
GET  /v1/admin/traces, /v1/admin/evals
```
Auth: internal service key (Django → service). No secret defaults in code.

---

## 9. Model & provider layer

- Thin provider interface: `chat()`, `chat_structured()`, `stream()`, `embed()`, `rerank()`.
- Implementations: OpenAI-compatible (covers OpenAI, local vLLM/Ollama via `LLMConfig`), Anthropic.
- Two roles, configured independently:
  - **fast** — query understanding, rewrite, enrichment, verification.
  - **strong** — final answer synthesis.
- Embedding model is fixed per index version; changing it triggers a background re-embed
  into a new column/index, then an atomic switch.
- Retries, timeouts, fallback provider, token & cost accounting per call → `trace`.

---

## 10. Performance

| Stage | Budget (p50) | Technique |
|---|---|---|
| Session load + rewrite | 150 ms | Redis; skip rewrite when no history |
| Query understanding | 250 ms | fast model, structured output, cached by normalized query |
| Retrieval (parallel sub-queries) | 120 ms | one SQL per sub-query, HNSW, filtered indexes, pooled async conn |
| Rerank | 150 ms | top-40 only, batched |
| First token | **< 1.5 s** | streaming; context built while plan finalizes |
| Full answer | < 6 s p95 | budgeted context, verifier on tail only |

Caching layers:
- Embedding cache (query text → vector), Redis, 24 h.
- Plan cache (normalized query + date bucket).
- **Answer cache** for briefing/latest intents keyed by `(intent, time window, corpus_version)`;
  `corpus_version` bumps on ingest, so caches never serve stale news.
- Precomputed daily briefing after each fetch cycle.

---

## 11. Observability & evaluation

- **Trace** every query: plan, filters, retrieved/reranked IDs and scores, context tokens,
  model, latency per stage, verifier verdicts, user feedback (👍/👎).
- **Eval suite** (`ai_service/evals/`), run in CI and before every prompt/model change:
  - Golden set built from real approved articles (~150 questions across all intents),
    including **unanswerable** and **time-trap** questions.
  - Metrics: retrieval recall@k, citation precision, faithfulness (claim support rate),
    temporal correctness, correct-refusal rate, latency, cost.
  - Baseline run against Scrutinize first, so improvement is measured, not assumed.

---

## 12. Repository layout

```
ai_service/
  architecture.md, plan.md
  pyproject.toml, Dockerfile, alembic.ini
  app/
    main.py                 FastAPI app, routers
    config.py               pydantic-settings (no secret defaults)
    api/                    ask.py, briefing.py, ingest.py, admin.py
    core/                   db.py (async pool), cache.py, auth.py, tracing.py
    providers/              base.py, openai_compat.py, anthropic.py, embeddings.py, rerank.py
    ingestion/              loader.py, cleaner.py, chunker.py, enricher.py, entities.py, stories.py, indexer.py
    query/                  conversation.py, understanding.py, timeparse.py, planner.py
    retrieval/              hybrid.py, filters.py, fusion.py, rerank.py, diversify.py, sql_first.py
    context/                builder.py, budget.py, formatting.py
    generation/             generator.py, prompts/ (versioned), streaming.py
    verification/           citations.py, claims.py, temporal.py
    workers/                tasks.py (ingest, reconcile, briefing precompute)
  migrations/               Alembic (schema "ai")
  evals/                    datasets/, runners/, metrics/, reports/
  tests/                    unit/, integration/
apps/ai/client.py           Django-side typed client (replaces apps/frontend/scrutinize.py)
```

---

## 13. Risks & mitigations

| Risk | Mitigation |
|---|---|
| Ingestion LLM cost on backfill | fast model, batch, skip unchanged hashes, cap backfill window |
| Neon cold starts / connection limits | pooled connections (Neon pooler), warm-up on deploy |
| pgvector recall under heavy filters | HNSW `ef_search` tuning + iterative scan; partial indexes on `status='approved'` |
| Story clustering errors | conservative thresholds, admin merge/split, eval cases |
| Verifier adds latency | only on tail/flagged sentences; async where possible |
| Two AI stacks during migration | feature flag + shadow mode; Scrutinize removed only after eval parity |

---

## 14. Implementation notes (where the build differs from the design above)

* **Relevance gate added** between ranking and context building (`retrieval/relevance.py`). The design assumed
  retrieval + reranking was enough; the eval harness showed that nearest-neighbour search always returns
  candidates, so invented entities got unrelated "evidence". The gate (entity must be mentioned; weak lexical *and*
  semantic overlap is dropped) makes "no evidence" a first-class outcome, and the context builder adds a coverage
  note naming entities with zero coverage.
* **Verification** treats calendar dates as metadata (checked by the temporal check), not as numeric claims; the
  service's own extractive fallback text is not run through the verifier.
* **No `Post.updated_at`**: reconcile uses `ai.article.content_hash` (includes title, body, tags, source, URL,
  date, pipeline version, embed model) so any change re-indexes with no Django migration.
* **Reranking** is LLM-listwise or an HTTP cross-encoder (TEI/Cohere/Jina format); no local model is bundled.
* **Jobs** use `arq` (Redis) rather than Celery inside the service; Django still uses Celery to *call* the service.
* **Plan cache** keys include `PLANNER_VERSION` and the prompt version, so changed logic never serves old plans.
* **Windows**: psycopg async needs the selector event loop; `antix_ai/__init__.py` sets the policy and the CLI
  starts uvicorn with `loop="none"` there.
