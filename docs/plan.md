# AI/Tech News Platform — Architecture 1 Build Plan

> Simple synchronous pipeline · Python + Jinja2 · Fly.io · Neon PostgreSQL · Redis · External cron

---

## Tech Stack

| Layer | Technology |
|---|---|
| Language | Python 3.12 |
| Web framework | Django 5.x |
| Templates | Jinja2 (via `django-jinja`) |
| Database | Neon PostgreSQL (serverless) |
| Cache / dedup | Redis — local Docker (dev) · co-located in Fly app (prod) |
| Task queue | Celery (broker = Redis) |
| Task scheduler | External cron (GitHub Actions, UptimeRobot, or cron-as-a-service) → HTTP trigger every 45 min |
| RSS parsing | `feedparser` |
| HTTP client | `httpx` |
| HTML parsing | `BeautifulSoup4` |
| Article extraction | `newspaper3k` + `readability-lxml` |
| AI layer | OpenAI API (`gpt-4o-mini`) |
| Deployment | Fly.io (Docker-based) |
| Static files | WhiteNoise |
| CSS | Bootstrap 5 (CDN) |

---

## Project Structure

```
ainews/
├── config/                  — Django project config (settings, urls, celery, wsgi)
│   └── settings/
│       ├── base.py
│       ├── development.py
│       └── production.py
│
├── apps/
│   ├── sources/             — Module 1: source management (background fetch)
│   ├── fetcher/             — Module 2: fetch + scrape + dedup (background)
│   ├── extractor/           — Module 3: LLM extraction (admin submit + fetch)
│   ├── posts/               — Module 4: post model + admin (add news UI)
│   └── frontend/            — Module 5: public feed
│
├── templates/               — global Jinja2 templates
├── static/
├── manage.py
├── requirements.txt
├── docker-compose.yml       — local Redis for development only
├── Dockerfile
├── fly.toml
└── .env.example
```

---

## Redis & Scheduling Architecture

Dev and production run **in parallel** with separate Redis instances. They never share state — local dedup/cache stays local; production dedup/cache stays on Fly.

### Redis — two environments, both active

| Environment | Redis location | `REDIS_URL` | Purpose |
|---|---|---|---|
| **Development** | Local Docker container (`docker compose up -d`) | `redis://localhost:6379/0` | Celery broker + URL dedup while coding locally |
| **Production (Fly.io)** | Redis co-located inside the backend Fly app (same machine as gunicorn) | `redis://127.0.0.1:6379/0` | Celery broker + URL dedup on the deployed app |

**Development setup**

```bash
docker compose up -d    # starts redis:7-alpine on localhost:6379
```

`.env` for local dev points at Docker Redis. Your Neon `DATABASE_URL` can still target a dev branch or shared Neon project — only Redis is fully local.

**Production setup**

- Redis runs as a sidecar process inside the Fly backend image (e.g. `supervisord` managing `redis-server` + `gunicorn`, or a `redis` process defined alongside `web` in `fly.toml` on the same machine).
- No Upstash or external Redis service — keeps cost at zero and avoids a second billable dependency.
- `REDIS_URL` is set to `redis://127.0.0.1:6379/0` via Fly `[env]` or secrets; Django/Celery connect over loopback.

### Scheduling — external cron wakes Fly, no Celery Beat

Fly.io machines on the free/low tier **auto-stop when idle**. Celery Beat inside a sleeping machine never fires. Instead:

1. Expose a protected HTTP endpoint on the Django app, e.g. `POST /internal/trigger-fetch/`.
2. Guard it with a shared secret header (`X-Cron-Secret` / `CRON_SECRET` env var) so random visitors cannot trigger fetches.
3. Configure a **free external cron** to `POST` that URL **every 45 minutes**:
   - **GitHub Actions** — `schedule: '*/45 * * * *'` workflow that `curl`s the endpoint
   - **UptimeRobot** — monitor hitting the endpoint on an interval (or a dedicated heartbeat monitor)
   - **cron-job.org / EasyCron** — any free cron-as-a-service that supports HTTP POST
4. Fly receives the inbound request → **wakes the sleeping machine** → Django validates the secret → dispatches `fetch_all_sources` (Celery) or runs the pipeline → machine goes back to sleep after inactivity.

```
External cron (every 45 min)
        │
        ▼ POST /internal/trigger-fetch/
Fly.io web machine (wakes from sleep)
        │
        ▼
Django validates CRON_SECRET
        │
        ▼
fetch_all_sources → Celery tasks → Redis dedup → Neon posts
        │
        ▼
Machine auto-stops after idle timeout
```

**Do not use Celery Beat in production.** Beat requires a process that stays awake 24/7, which defeats Fly auto-stop savings. Local dev can trigger fetches manually (`curl` the endpoint, Django shell, or `fetch_all_sources.delay()`) — no Beat needed locally either.

---

## News Tags (10 fixed tech categories)

Every news item is tagged with **one or more** tags from this fixed list. Tags are used for filtering on the public feed and are assigned by the LLM during extraction. Admin can add or correct tags in the warning popup when the LLM misses them.

| # | Tag | What it covers |
|---|---|---|
| 1 | **LLMs** | Large language models, chatbots, GPT, Claude, Gemini, etc. |
| 2 | **Computer Vision** | Image/video AI, object detection, generative image models |
| 3 | **Robotics** | Autonomous systems, drones, humanoid robots, industrial automation |
| 4 | **Cloud & Infra** | Cloud platforms, GPUs, data centers, MLOps, deployment |
| 5 | **Cybersecurity** | AI security, vulnerabilities, privacy, adversarial ML |
| 6 | **Startups & Funding** | Company launches, acquisitions, funding rounds, IPOs |
| 7 | **Open Source** | Open models, frameworks, libraries, community projects |
| 8 | **Research** | Papers, benchmarks, academic breakthroughs, labs |
| 9 | **Developer Tools** | IDEs, APIs, SDKs, coding assistants, dev workflows |
| 10 | **Policy & Ethics** | Regulation, safety, bias, governance, societal impact |

Stored in the database as a JSON array of tag slugs (e.g. `["llms", "startups-funding"]`). A post must have at least one tag before it is published.

---

## Database Schema (what tables you need and why)

### Source table
Stores every news source the background fetcher knows about. Fields needed: name, homepage URL, RSS URL (nullable), source type (official / media / blog / community / research), badge label, active flag, fetch interval in minutes, and last fetched timestamp. Used only by the automated fetch pipeline — not exposed in the admin add-news UI.

### Post table
One row per article. Fields needed: foreign key to Source (nullable — manual admin submissions have no source), title, original URL (unique when present — the canonical dedup anchor), author, publish date, fetch date, raw input text (link content or pasted text/XML/JSON), AI-generated summary, tags (JSON array of slugs from the 10-tag list above), status (pending / approved / rejected), and a SHA-256 hash of the original URL for fast dedup lookups. Index on `(status, published_at)` for the public feed query. Index on `url_hash` for dedup checks. GIN index on `tags` for tag-filter queries.

---

## Phase 0 — Project Bootstrap

**Goal:** A deployable Django project connected to Neon and Redis (local Docker in dev, co-located on Fly in prod) with Celery configured. No business logic yet.

### What to do

- Create a new Django project skeleton using `django-admin startproject`
- Set up three settings files: `base.py` for shared settings, `development.py` for local, `production.py` for Fly.io
- Configure the database connection to read `DATABASE_URL` from environment (Neon gives you this)
- Configure Redis connection to read `REDIS_URL` from environment:
  - **Dev:** `redis://localhost:6379/0` (Docker Compose)
  - **Prod:** `redis://127.0.0.1:6379/0` (co-located Redis in the Fly app)
- Write `docker-compose.yml` with a single `redis:7-alpine` service on port 6379 for local development
- Configure Jinja2 as the template backend via `django-jinja`
- Set up Celery to use Redis as both the broker and result backend (**no Celery Beat**)
- Configure WhiteNoise for serving static files without a CDN
- Write a `Dockerfile` — Python 3.12 slim base, install system deps (`libpq-dev`, `gcc`, `redis-server`), install Python deps, run `collectstatic`, expose port 8000; use `supervisord` (or equivalent) to run **redis-server + gunicorn + celery worker** in the same container on Fly
- Write `fly.toml` — single `web` process (no separate worker machine; Celery worker runs inside the same Fly app alongside Redis)
- Set Fly secrets: `DATABASE_URL`, `OPENAI_API_KEY`, `SECRET_KEY`, `ALLOWED_HOSTS`, `CRON_SECRET`
- Set Fly `[env]`: `REDIS_URL=redis://127.0.0.1:6379/0` (loopback to co-located Redis)
- Deploy and confirm the web process starts, Redis is reachable on loopback, and Celery worker connects

**Exit criteria:** Django admin loads at your Fly URL. `redis-cli -h 127.0.0.1 ping` works inside the Fly machine. Celery worker logs show it connected to local Redis. `docker compose up -d` + local `manage.py runserver` connects to Docker Redis on the dev machine.

---

## Phase 1 — Module 1: Source Management (background)

**Goal:** Seed and manage news sources for the automated background fetcher. This is **not** part of the admin add-news UI — sources are configured once via management command and maintained only when a feed breaks.

### What to do

- Create the `Source` model with all fields described in the schema above
- Register `Source` in Django admin (read-only list for debugging — not the primary admin workflow)
- Write a Django management command called `seed_sources` that creates all 19 sources with their correct RSS URLs, source types, and badge labels from the RSS reference table
- For the 3 sources with no RSS (Meta AI, Mistral AI, xAI), leave `rss_url` null and set only the homepage URL
- Run migrations and execute the seed command to confirm all 19 sources exist

**Exit criteria:** All 19 sources exist in the database. Background fetch can reference them. Admin add-news UI is not built yet.

---

## Phase 2 — Module 2: Fetch Pipeline (background)

**Goal:** A Celery task that, on a schedule, fetches articles from all active sources, deduplicates them via Redis, scrapes full article text, and saves raw posts to the database with `status=pending`. Runs in the background — admin does not interact with this directly.

### What to do

This module has four sub-components that you build in this order:

#### 2a — URL deduplication (`apps/fetcher/dedup.py`)

- Write a function that takes a URL, hashes it with SHA-256, and does a Redis `SADD` on a set key
- `SADD` returns 1 if the URL was new, 0 if it already existed — use this as your duplicate check
- Set a TTL of 30 days on the Redis set so old URLs eventually expire and can be re-fetched
- This function is called before any scraping happens — if it returns duplicate, skip that URL entirely and move on

#### 2b — RSS fetcher (`apps/fetcher/rss.py`)

- Write a function that takes an RSS URL and uses `feedparser` to parse it
- Extract from each entry: link, title, published date, and the short snippet/summary from the feed
- Return a list of lightweight data objects (one per entry) with these four fields
- Handle malformed dates gracefully — return None if the date cannot be parsed

#### 2c — HTML scraper for no-RSS sources (`apps/fetcher/scraper.py`)

- Write a function that takes a homepage URL, fetches it with `httpx`, parses it with `BeautifulSoup`, and returns a list of article links found on the page
- Cap at 30 candidate links per source to avoid runaway scraping
- Write a second function that takes a single article URL and extracts clean body text using `newspaper3k`
- If `newspaper3k` fails (JavaScript-heavy page, paywalled, etc.), fall back to `readability-lxml` which handles more edge cases
- Cap the extracted text at 8000 characters before passing it to the LLM — longer than that adds cost without improving quality

#### 2d — Main Celery task (`apps/fetcher/tasks.py`)

- Write a task called `fetch_all_sources` that queries all active `Source` rows and dispatches a per-source sub-task for each one
- Write a task called `fetch_source` that receives a single source ID and does the full pipeline for that one source:
  1. If the source has an `rss_url`, call the RSS fetcher to get article links
  2. If no `rss_url`, call the HTML scraper to get article links from the homepage
  3. For each link, call the dedup check — skip if duplicate
  4. For new links, call the article text extractor to get full body text
  5. Call the LLM extractor (Module 3) with the text — get back structured metadata
  6. Save a `Post` row with `status=pending`
  7. Update `Source.last_fetched_at` to now
- Add retry logic: if a fetch fails (network error, timeout), retry up to 3 times with a 5-minute delay
- Log how many new posts were saved per source

#### 2e — HTTP trigger endpoint (replaces Celery Beat)

- Add a view at `POST /internal/trigger-fetch/` (not linked in public UI)
- Validate `X-Cron-Secret` header against `CRON_SECRET` env var; return `403` if missing or wrong
- On success, dispatch `fetch_all_sources.delay()` and return `202 Accepted` with a JSON body (`{"status": "dispatched"}`)
- Keep the endpoint fast — it only enqueues work; the Celery worker on the same machine processes tasks after Fly wakes up
- **Do not configure `CELERY_BEAT_SCHEDULE`** — scheduling is external

#### 2f — External cron (every 45 minutes)

- Set up one free external scheduler to `POST` the trigger endpoint every **45 minutes**:
  - **GitHub Actions** (recommended if repo is on GitHub):

    ```yaml
    # .github/workflows/trigger-fetch.yml
    on:
      schedule:
        - cron: '*/45 * * * *'
    jobs:
      trigger:
        runs-on: ubuntu-latest
        steps:
          - run: |
              curl -sf -X POST \
                -H "X-Cron-Secret: ${{ secrets.CRON_SECRET }}" \
                https://your-app.fly.dev/internal/trigger-fetch/
    ```

  - **UptimeRobot** — create an HTTP monitor pointed at the endpoint (custom interval if supported, or combine with a cron service)
  - **cron-job.org / EasyCron** — free tier HTTP cron with 45-minute interval
- Store `CRON_SECRET` in GitHub Actions secrets and Fly secrets (same value in both places)
- Result: Fly sees the inbound request every 45 min → wakes the sleeping machine → fetch runs → machine sleeps again when idle

**Exit criteria:** Hitting the trigger endpoint manually (with correct secret) creates new `Post` rows with `status=pending`. After external cron is configured, Fly logs show wake → fetch → sleep cycles every ~45 minutes.

---

## Phase 3 — Module 3: LLM Extraction

**Goal:** Given a URL, pasted text, XML, or JSON, GPT-4o mini validates whether the content is real tech/AI news, extracts structured metadata, and returns a JSON object. If required fields or tags are missing, the admin UI shows a warning popup so the user can fill them in before saving.

### What to do

- Write the prompt in a separate `prompts.py` file so it is easy to iterate on without touching logic
- The prompt should instruct GPT-4o mini to:
  1. Decide if the input is valid tech/AI news — return `is_valid_news: false` with a reason if not
  2. Return only a JSON object — no markdown fences, no explanation, no preamble
- The JSON object should have exactly these fields:
  - `is_valid_news` (boolean)
  - `title` (max 120 chars)
  - `author` (or null)
  - `published_at` (ISO 8601 or null)
  - `summary` (3 sentences max, factual, no hype)
  - `tags` (array of 1–5 slugs from the 10-tag list above — must use only valid slugs)
  - `missing_fields` (array of field names the LLM could not determine, e.g. `["author", "tags"]`)
- For URL input: fetch the page with `httpx`, extract article text with `newspaper3k` / `readability-lxml`, then pass text to the LLM
- For pasted text input: pass directly to the LLM — supports plain text, XML (RSS/Atom feeds), and JSON (API responses, structured feeds)
- Write the OpenAI client function using the `openai` Python SDK, model `gpt-4o-mini`, that sends the prompt, reads the response, and parses the JSON
- Add a fallback JSON parser: if the model wraps output in ```json fences despite instructions, strip the fences and parse again
- Parse the `published_at` string to a Python datetime using `python-dateutil`
- Validate returned tags against the 10-tag allowlist — strip any invalid slugs and add `"tags"` to `missing_fields` if the result is empty
- This function is called from both the admin add-news form (Phase 4) and the background `fetch_source` task (Phase 2d)

**Exit criteria:** Call the function manually in a Django shell with a real URL and a pasted XML feed snippet. Confirm it returns a valid dict, assigns correct tags, and flags missing fields when appropriate.

---

## Phase 4 — Module 4: Admin — Add News (primary admin workflow)

**Goal:** The admin panel has one primary job: **add news**. Admin pastes a URL or raw text (plain text, XML, or JSON), GPT-4o mini reads it, and if it is valid news the system prepares a post for upload. If fields or tags are missing, a warning popup lets the admin fill them in before saving.

### What to do

- Create the `Post` model with all fields described in the schema section
- Add the database indexes: `(status, published_at)`, `url_hash`, and GIN on `tags`
- Build a custom admin view (not the default changelist) as the admin landing page — **"Add News"**
- The add-news form has two input modes (toggle or tabs):
  - **URL** — single text field; backend fetches and extracts article text
  - **Text** — large textarea; accepts plain text, XML, or JSON pasted directly
- On submit, call the LLM extractor (Phase 3) synchronously and return a preview JSON to the browser
- **Validation popup flow:**
  - If `is_valid_news` is `false` → show an error alert with the LLM's reason; do not save
  - If `is_valid_news` is `true` but `missing_fields` is non-empty → show a **warning popup** listing which fields are missing (e.g. "Author and tags could not be determined")
  - The popup renders editable inputs for every missing field plus a multi-select for tags (all 10 tags shown as checkboxes)
  - Admin fills in the gaps and clicks **"Confirm & Publish"** to save the post with `status=approved`
  - If nothing is missing → show a clean preview card and a single **"Publish"** button
- Preview card shows: title, author, publish date, summary, and selected tag chips before confirm
- Do **not** build a full post review/approve/reject workflow in admin — the only admin action is adding news
- Keep a minimal read-only post list in admin for debugging (title, tags, publish date) but no bulk approve/reject UI

**Exit criteria:** Admin opens `/admin`, sees the Add News form, pastes a URL, gets a preview. A post with missing tags triggers the warning popup with tag checkboxes. After filling tags and confirming, the post appears on the public feed.

---

## Phase 5 — Module 5: Public Feed (Frontend)

**Goal:** A clean, fast, server-rendered public feed showing all approved posts. Visitors can filter by tag, search, and click through to original articles.

### What to do

- Write a `FeedView` (Django ListView) that queries `Post` objects with `status=approved`, ordered by publish date descending, paginated at 20 per page
- Support two optional query parameters:
  - `tag` — filter by one or more tag slugs (e.g. `?tag=llms&tag=research`); posts matching **any** selected tag are shown
  - `q` — keyword search across title and summary
- Pass the full list of 10 tags (slug + display name) to the template so the filter bar is always populated
- Write three Jinja2 templates:
  - `base.html` — navbar with the site name, Bootstrap CSS from CDN, content block
  - `feed.html` — filter bar (search input, tag chip toggles for all 10 tags, submit button), grid of post cards, pagination controls
  - `post_card.html` — the individual card showing: post title, AI summary, tags as coloured chips, publish date, and a "Read Full Article →" button that opens `original_url` in a new tab with `rel="noopener noreferrer"` (hidden if no URL was provided)
- The "Read Full Article" button links directly to `post.original_url` — never proxy or cache the article content
- Wire up the URL config so the feed is served at `/`
- Make sure filtering preserves other active filters (e.g. selecting a tag while a search query is active keeps the search query)
- Highlight active tag chips in the filter bar when selected

**Exit criteria:** The public feed loads at your Fly URL. Tag filter chips work — selecting "LLMs" and "Research" shows posts tagged with either. Search works. Pagination works. The read button opens the original article.

---

## Phase 6 — Deployment on Fly.io

**Goal:** Production on Fly.io with co-located Redis, external cron scheduling, and dev/prod Redis running independently.

### What to do

#### Local development (runs alongside production — separate Redis)

```bash
docker compose up -d          # local Redis on :6379
cp .env.example .env          # REDIS_URL=redis://localhost:6379/0
python manage.py runserver
celery -A config worker -l info   # optional: process tasks locally
```

Dev and prod do not share Redis or dedup state. You can develop locally while production cron keeps waking the Fly app on its own schedule.

#### Dockerfile (production image)
- Use `python:3.12-slim` as base
- Install system dependencies: `libpq-dev`, `gcc`, `curl`, `redis-server`, `supervisor`
- Copy and install Python requirements
- Run `collectstatic` during build so static files are baked in
- Configure `supervisord` to manage three programs in one container:
  1. `redis-server` (bind `127.0.0.1:6379`)
  2. `gunicorn` on port 8000
  3. `celery -A config worker` (concurrency 2, **no `-B` beat flag**)

#### fly.toml
- Single `web` process running supervisord (Redis + gunicorn + Celery worker in one machine)
- Configure the `web` service to accept HTTP on port 80 and HTTPS on port 443
- Enable `auto_stop_machines` and `auto_start_machines` so the machine sleeps when idle and wakes on cron HTTP hits
- Set memory to 512MB per machine
- Set `DJANGO_SETTINGS_MODULE` to production settings in `[env]`
- Set `REDIS_URL=redis://127.0.0.1:6379/0` in `[env]` (not a secret — loopback only)

#### Fly secrets
- Set via `fly secrets set`:
  - `DATABASE_URL` — Neon pooled connection string
  - `OPENAI_API_KEY`
  - `SECRET_KEY`
  - `ALLOWED_HOSTS`
  - `CRON_SECRET` — shared with GitHub Actions / external cron provider
- **Do not set `REDIS_URL` as a Fly secret** — use `[env]` loopback default above
- Never commit secrets to the repo

#### External cron setup (after first deploy)
- Add `CRON_SECRET` to GitHub Actions repository secrets (or your cron provider's vault)
- Deploy the `.github/workflows/trigger-fetch.yml` workflow (45-minute schedule)
- Confirm first cron run wakes the machine: `fly logs` should show an HTTP `POST /internal/trigger-fetch/` followed by fetch task logs
- Optionally add UptimeRobot as a backup monitor on the same endpoint

#### After first deploy
- SSH into the Fly machine and run database migrations
- Create a Django superuser for admin access
- Run the `seed_sources` management command to populate all 19 sources
- Test the add-news form end-to-end
- Manually `curl` the trigger endpoint to confirm fetch pipeline works before relying on cron

#### Ongoing
- Every code change: `fly deploy`
- Check `fly logs` after deploy and after cron fires
- Use `fly ssh console` for ad-hoc management commands
- Local dev continues on Docker Redis — unaffected by production deploys

**Exit criteria:** Public feed live at `https://your-app.fly.dev`. External cron hits the trigger endpoint every 45 minutes. Fly logs show wake → fetch → idle-stop cycles. Local `docker compose` Redis works independently for development.

---

## Phase Summary

| Phase | Module | What it delivers |
|---|---|---|
| 0 | Bootstrap | Django on Fly.io + Neon; Docker Redis (dev) + co-located Redis (prod) |
| 1 | Sources | 19 sources seeded for background fetch (not admin UI) |
| 2 | Fetcher | Celery fetch pipeline + HTTP trigger; external cron every 45 min wakes Fly |
| 3 | LLM Extractor | GPT-4o mini validates news, extracts title/author/date/summary/tags, flags missing fields |
| 4 | Admin Add News | Primary admin UI: paste URL or text → LLM preview → warning popup for missing fields → publish |
| 5 | Frontend | Public Jinja2 feed with 10-tag filtering, search, pagination, and read-through links |
| 6 | Deployment | Fly.io with co-located Redis, external cron, dev Docker Redis in parallel |

---

## Recommended Build Order

```
Phase 0 → Phase 4 (model + add-news UI) → Phase 3 → Phase 5 → Phase 1 → Phase 2 → Phase 6
```

Build the `Post` model and the add-news admin UI first — that is the core product. Build the LLM extractor next so the form works. Build the public feed so published posts are visible. Add the background fetch pipeline last; it is a nice-to-have automation layer, not the primary workflow.

---

## Key Design Decisions

- **Admin panel = add news only.** No source management, no approve/reject queue in the primary UI. Admin pastes a link or text, LLM does the rest, warning popup handles gaps.
- **Two input modes.** URL (fetched automatically) or pasted text/XML/JSON (passed directly to the LLM). Covers RSS feeds, API JSON responses, and plain article text.
- **10 fixed tags, multiple per post.** Tags are the only categorisation dimension. Each post gets 1–5 tags from the allowlist. Public feed filters by tag.
- **Warning popup, not silent defaults.** When the LLM cannot determine a field (especially tags), show a popup with editable inputs rather than saving incomplete data.
- **GPT-4o mini for extraction.** Fast and cheap. Good enough for structured JSON extraction and news validation. Upgrade to `gpt-4o` only if quality is poor on edge cases.
- **Synchronous tasks only.** No async, no threading inside tasks. Easier to debug when something breaks.
- **External cron, not Celery Beat.** Fly machines auto-stop when idle; Beat would never fire. A free external cron POSTs every 45 minutes to wake the machine and trigger fetches.
- **Two Redis instances, both always available.** Dev uses Docker Redis on `localhost`; production uses Redis co-located inside the Fly backend app on `127.0.0.1`. They run simultaneously but never share data.
- **Redis as dedup + Celery broker only.** No page caching in Architecture 1. No Upstash or paid external Redis.
- **newspaper3k first, readability fallback.** newspaper3k handles most well-structured articles. readability-lxml handles more edge cases.
- **Neon free tier is sufficient for MVP.** Neon auto-pauses the database when idle and resumes on first query. Adds ~500ms cold start latency which is acceptable for a low-traffic MVP.
- **No full-article storage beyond raw_content.** You store the scraped/pasted text for LLM processing and debugging, but never display it publicly. The "Read Full Article" button always sends users to the original source.
