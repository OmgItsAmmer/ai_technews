# AI/Tech News Platform — Architecture 1 Build Plan

> Simple synchronous pipeline · Python + Jinja2 · Fly.io · Neon PostgreSQL · Redis · Celery

---

## Tech Stack

| Layer | Technology |
|---|---|
| Language | Python 3.12 |
| Web framework | Django 5.x |
| Templates | Jinja2 (via `django-jinja`) |
| Database | Neon PostgreSQL (serverless) |
| Cache / dedup | Redis (Upstash free tier recommended) |
| Task scheduler | Celery + Celery Beat |
| RSS parsing | `feedparser` |
| HTTP client | `httpx` |
| HTML parsing | `BeautifulSoup4` |
| Article extraction | `newspaper3k` + `readability-lxml` |
| AI layer | Anthropic Claude API (`claude-haiku-4-5-20251001`) |
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
│   ├── sources/             — Module 1: source management
│   ├── fetcher/             — Module 2: fetch + scrape + dedup
│   ├── extractor/           — Module 3: LLM extraction
│   ├── posts/               — Module 4: post model + admin
│   └── frontend/            — Module 5: public feed
│
├── templates/               — global Jinja2 templates
├── static/
├── manage.py
├── requirements.txt
├── Dockerfile
├── fly.toml
└── .env.example
```

---

## Database Schema (what tables you need and why)

### Source table
Stores every news source the system knows about. Fields needed: name, homepage URL, RSS URL (nullable — some sources have no RSS), source type (official / media / blog / community / research), badge label, active flag, fetch interval in minutes, and last fetched timestamp. The active flag lets admin disable a broken source without deleting it.

### Post table
One row per article the system has processed. Fields needed: foreign key to Source, title, original URL (unique — the canonical dedup anchor), author, publish date, fetch date, raw article text, AI-generated summary, category, tags (stored as JSON array), status (pending / approved / rejected), and a SHA-256 hash of the original URL for fast dedup lookups. Index on `(status, published_at)` for the public feed query. Index on `url_hash` for dedup checks.

---

## Phase 0 — Project Bootstrap

**Goal:** A deployable, empty Django project connected to Neon and Redis with Celery running. No business logic yet.

### What to do

- Create a new Django project skeleton using `django-admin startproject`
- Set up three settings files: `base.py` for shared settings, `development.py` for local, `production.py` for Fly.io
- Configure the database connection to read `DATABASE_URL` from environment (Neon gives you this)
- Configure Redis connection to read `REDIS_URL` from environment
- Configure Jinja2 as the template backend via `django-jinja`
- Set up Celery to use Redis as both the broker and result backend
- Configure WhiteNoise for serving static files without a CDN
- Write a `Dockerfile` — Python 3.12 slim base, install system deps (`libpq-dev`, `gcc`), install Python deps, run `collectstatic`, expose port 8000, start gunicorn
- Write `fly.toml` — define two processes: `web` (gunicorn) and `worker` (celery with `-B` flag so beat runs in the same process as the worker)
- Set all secrets on Fly: `DATABASE_URL`, `REDIS_URL`, `ANTHROPIC_API_KEY`, `SECRET_KEY`, `ALLOWED_HOSTS`
- Deploy and confirm both processes start without errors

**Exit criteria:** Django admin loads at your Fly URL. Celery worker logs show it connected to Redis successfully.

---

## Phase 1 — Module 1: Source Management

**Goal:** Admin can add, edit, enable, and disable news sources. All 19 sources from the RSS reference pre-loaded.

### What to do

- Create the `Source` model with all fields described in the schema above
- Register `Source` in Django admin with list display showing name, type, badge, active status, and last fetched time
- Add list filters for source type and active status
- Add search by name and URL
- Add bulk actions to activate and deactivate multiple sources at once
- Write a Django management command called `seed_sources` that creates all 19 sources with their correct RSS URLs, source types, and badge labels from the RSS reference table
- For the 3 sources with no RSS (Meta AI, Mistral AI, xAI), leave `rss_url` null and set only the homepage URL
- Run migrations and execute the seed command to confirm all 19 sources appear in admin

**Exit criteria:** Admin shows all 19 sources. Active/inactive toggle works. No fetch logic yet.

---

## Phase 2 — Module 2: Fetch Pipeline

**Goal:** A Celery task that, on a schedule, fetches articles from all active sources, deduplicates them via Redis, scrapes full article text, and saves raw posts to the database with `status=pending`.

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

#### 2e — Celery Beat schedule

- Configure Celery Beat in settings to run `fetch_all_sources` every 4 hours via a crontab schedule
- Since the worker is started with `-B`, beat runs alongside the worker in the same process on Fly.io — no separate process needed

**Exit criteria:** After starting the worker, wait 4 hours (or trigger manually via Django shell). New `Post` rows appear in admin with `status=pending` and populated `raw_content`.

---

## Phase 3 — Module 3: LLM Extraction

**Goal:** Given raw article text, Claude returns a structured JSON object with title, author, date, summary, category, and tags.

### What to do

- Write the prompt in a separate `prompts.py` file so it is easy to iterate on without touching logic
- The prompt should instruct Claude to return only a JSON object — no markdown fences, no explanation, no preamble
- The JSON object should have exactly these fields: title (max 120 chars), author (or null), published_at (ISO 8601 or null), summary (3 sentences max, factual, no hype), category (one of a fixed list you define), tags (up to 5 specific tags — model names, company names, technique names)
- Include the source name and URL in the prompt so Claude has context about where the article came from
- Write the LLM client function that sends the prompt to Claude Haiku, reads the response, and parses the JSON
- Add a fallback JSON parser: if Claude wraps the output in ```json fences despite instructions, strip the fences and parse again
- Parse the `published_at` string to a Python datetime using `python-dateutil` — it handles most date formats automatically
- This function is called from the `fetch_source` task (Phase 2d) for every new article

**Exit criteria:** Call the function manually in a Django shell against one real scraped article. Confirm it returns a valid dict with all expected fields.

---

## Phase 4 — Module 4: Post Management (Admin)

**Goal:** Admin can see all pending posts, read the AI-generated summary, edit fields if needed, and approve or reject posts. Only approved posts become public.

### What to do

- Create the `Post` model with all fields described in the schema section
- Add the two database indexes: one on `(status, published_at)` for the feed query, one on `url_hash` for dedup
- Register `Post` in Django admin with these list columns: title, source name, category, status, publish date, fetch date
- Add filters for status, source, and category
- Add full-text search across title, summary, and author
- Make `status` editable directly in the list view so admin can approve/reject without opening each post individually
- Add bulk actions: "Approve selected" and "Reject selected" for processing many posts at once
- In the detail view, show: title (editable), summary (editable), category (editable), tags (editable), author, original URL (read-only link), publish date, and the raw article text collapsed in a section (read-only, for reference)
- Mark `url_hash`, `raw_content`, and `fetched_at` as read-only — admin should not change these

**Exit criteria:** Admin can see pending posts, edit the summary if Claude got something wrong, and bulk-approve a batch. Status changes to `approved` immediately.

---

## Phase 5 — Module 5: Public Feed (Frontend)

**Goal:** A clean, fast, server-rendered public feed showing all approved posts. Visitors can filter, search, and click through to original articles.

### What to do

- Write a `FeedView` (Django ListView) that queries `Post` objects with `status=approved`, ordered by publish date descending, paginated at 20 per page
- Support three optional query parameters: `category` (filter by category), `type` (filter by source type), `q` (keyword search across title and summary)
- Pass the list of distinct categories to the template so the filter dropdown is populated dynamically
- Write three Jinja2 templates:
  - `base.html` — navbar with the site name, Bootstrap CSS from CDN, content block
  - `feed.html` — filter bar (search input, category dropdown, source type dropdown, submit button), grid of post cards, pagination controls
  - `post_card.html` — the individual card showing: source badge (coloured by source type), source name, post title, AI summary, tags as small chips, publish date, and a "Read Full Article →" button that opens `original_url` in a new tab with `rel="noopener noreferrer"`
- The "Read Full Article" button should link directly to `post.original_url` — this is the entire point of the platform, never proxy or cache the article content
- Wire up the URL config so the feed is served at `/`
- Make sure filtering preserves other active filters (e.g. selecting a category while a search query is active keeps the search query)

**Exit criteria:** The public feed loads at your Fly URL. Cards show correct badge colours per source type. Filtering works. Pagination works. The read button opens the original article.

---

## Phase 6 — Deployment on Fly.io

**Goal:** Everything running in production on Fly.io with environment properly configured.

### What to do

#### Dockerfile
- Use `python:3.12-slim` as base
- Install system dependencies: `libpq-dev` (for psycopg2), `gcc`, `curl`
- Copy and install Python requirements
- Run `collectstatic` during build so static files are baked in
- Set the default command to gunicorn on port 8000

#### fly.toml
- Define two named processes under `[processes]`: `web` runs gunicorn, `worker` runs celery with the `-B` beat flag and concurrency of 2
- Configure the `web` service to accept HTTP on port 80 and HTTPS on port 443
- Set memory to 512MB per machine — enough for this workload
- Set `DJANGO_SETTINGS_MODULE` to production settings in `[env]`

#### Fly secrets
- Set all secrets via `fly secrets set`: `DATABASE_URL` (from Neon dashboard), `REDIS_URL` (from Upstash dashboard), `ANTHROPIC_API_KEY`, `SECRET_KEY`, `ALLOWED_HOSTS`
- Never commit these to the repo — they live only in Fly's secret store

#### After first deploy
- SSH into the web machine and run database migrations
- Create a Django superuser for admin access
- Run the `seed_sources` management command to populate all 19 sources
- Trigger a manual fetch from the Django shell to confirm the full pipeline works end-to-end
- Check Fly logs to confirm the Celery worker connected to Redis and the beat scheduler started

#### Ongoing
- Every code change: `fly deploy` — Fly does a rolling restart with zero downtime
- Check `fly logs` if anything breaks
- Use `fly ssh console` for any ad-hoc management commands

**Exit criteria:** Public feed live at `https://your-app.fly.dev`. Admin accessible at `/admin`. Celery worker logs show scheduled fetches running every 4 hours.

---

## Phase Summary

| Phase | Module | What it delivers |
|---|---|---|
| 0 | Bootstrap | Deployable Django skeleton on Fly.io connected to Neon + Redis |
| 1 | Sources | Admin UI to manage all 19 sources, seed command pre-loads them |
| 2 | Fetcher | Scheduled Celery task scrapes RSS + HTML, deduplicates via Redis, saves raw posts |
| 3 | LLM Extractor | Claude Haiku extracts title, author, date, summary, category, tags from article text |
| 4 | Post Admin | Admin can review, edit, approve, or reject pending posts |
| 5 | Frontend | Public Jinja2 feed with filtering, search, pagination, and read-through links |
| 6 | Deployment | Production live on Fly.io with secrets, migrations, and sources seeded |

---

## Recommended Build Order

```
Phase 0 → Phase 1 → Phase 4 (model + migration only) → Phase 2 → Phase 3 → Phase 5 → Phase 6
```

Build the `Post` model before the fetcher so the task has somewhere to write. Build the fetcher before the LLM extractor so you can test scraping independently. Build the frontend only after you have real approved posts in the database to display.

---

## Key Design Decisions

- **Synchronous tasks only.** No async, no threading inside tasks. Easier to debug when something breaks. Upgrade later if needed.
- **One worker process with beat.** Celery's `-B` flag runs the scheduler inside the worker. Saves a Fly machine and simplifies the setup.
- **Redis as dedup only.** In this architecture Redis does one job — track seen URL hashes. No page caching, no rate limiting. Add those in Architecture 2 if needed.
- **Claude Haiku for extraction.** Fastest and cheapest Claude model. If summary quality is poor on a specific source type, switch that source to Sonnet selectively.
- **newspaper3k first, readability fallback.** newspaper3k handles most well-structured articles. readability-lxml handles more edge cases like news aggregators and blog platforms.
- **Neon free tier is sufficient for MVP.** Neon auto-pauses the database when idle and resumes on first query. Adds ~500ms cold start latency which is acceptable for a low-traffic MVP.
- **No full-article storage beyond raw_content.** You store the scraped text for LLM processing and debugging, but never display it publicly. The "Read Full Article" button always sends users to the original source.