# AI/Tech News Platform — Architecture 1 Build Plan

> Manual add-news admin · Python + Jinja2 · Fly.io · Neon PostgreSQL · Claude

---

## MVP Scope (what we build first)

**Admin does one thing:** add news.

1. Admin pastes a **URL** or **raw text** (plain text, XML, JSON, HTML — whatever they have).
2. The system fetches/passes content to Claude.
3. Claude decides if it is real AI/tech news and extracts structured fields.
4. If required fields are missing or low-confidence, show a **warning popup** so the admin can fill in or correct fields before saving.
5. Saved posts appear on the public feed.

**Explicitly out of scope for Architecture 1:**

- Automated RSS/source fetching (Celery, Beat, Redis dedup)
- Source management UI (19 pre-seeded sources, enable/disable)
- Bulk approve/reject moderation queue
- Background workers

Those move to Architecture 2 once manual add-news works end-to-end.

---

## Tech Stack

| Layer | Technology |
|---|---|
| Language | Python 3.12 |
| Web framework | Django 5.x |
| Templates | Jinja2 (via `django-jinja`) |
| Database | Neon PostgreSQL (serverless) |
| HTTP client | `httpx` |
| HTML/article extraction | `newspaper3k` + `readability-lxml` (URL input only) |
| AI layer | Anthropic Claude API (`claude-haiku-4-5-20251001`) |
| Deployment | Fly.io (Docker-based) |
| Static files | WhiteNoise |
| CSS | Bootstrap 5 (CDN) |

> Redis and Celery are **not needed** for Architecture 1. Add them in Architecture 2 when automated fetching ships.

---

## Project Structure

```
ainews/
├── config/                  — Django project config (settings, urls, wsgi)
│   └── settings/
│       ├── base.py
│       ├── development.py
│       └── production.py
│
├── apps/
│   ├── posts/               — Post model + add-news admin flow
│   ├── extractor/           — LLM extraction + validation
│   └── frontend/            — Public feed
│
├── templates/
│   ├── admin/               — Add-news form + missing-fields warning modal
│   └── frontend/            — Public feed templates
├── static/
├── manage.py
├── requirements.txt
├── Dockerfile
├── fly.toml
└── .env.example
```

---

## Database Schema

### Post table

One row per news item. Fields:

| Field | Notes |
|---|---|
| `title` | Required |
| `original_url` | Nullable — only when input was a URL |
| `author` | Nullable |
| `published_at` | Nullable |
| `summary` | AI-generated, 3 sentences max |
| `category` | One of a fixed list |
| `tags` | JSON array, up to 5 |
| `raw_content` | Original text sent to the LLM (for debugging) |
| `status` | `approved` only for MVP — no moderation queue |
| `created_at` | When admin added it |

Index on `(status, published_at)` for the public feed query.

No `Source` table in Architecture 1. Source name/type can be inferred by the LLM from the content or entered manually in the warning popup if missing.

---

## Phase 0 — Project Bootstrap

**Goal:** Deployable Django project connected to Neon. No business logic yet.

### What to do

- Create Django project skeleton
- Settings split: `base.py`, `development.py`, `production.py`
- Database via `DATABASE_URL` from environment (Neon)
- Jinja2 via `django-jinja`
- WhiteNoise for static files
- `Dockerfile` — Python 3.12 slim, `libpq-dev`, gunicorn on port 8000
- `fly.toml` — single `web` process only (no worker)
- Fly secrets: `DATABASE_URL`, `ANTHROPIC_API_KEY`, `SECRET_KEY`, `ALLOWED_HOSTS`

**Exit criteria:** Django admin loads at your Fly URL.

---

## Phase 1 — Post Model

**Goal:** Database ready to store news.

### What to do

- Create `Post` model with fields above
- Migration + index on `(status, published_at)`
- Register a minimal read-only `Post` list in Django admin (title, category, created_at) — for debugging only, not the main workflow

**Exit criteria:** Can create a `Post` row via Django shell.

---

## Phase 2 — LLM Extraction

**Goal:** Given raw content, Claude returns structured news metadata or rejects non-news.

### What to do

- Prompt lives in `apps/extractor/prompts.py`
- Claude returns **only JSON** — no markdown fences, no preamble
- Response shape:

```json
{
  "is_news": true,
  "rejection_reason": null,
  "title": "...",
  "author": null,
  "published_at": "2026-01-15T00:00:00Z",
  "summary": "...",
  "category": "models",
  "tags": ["gpt-5", "openai"],
  "missing_fields": ["author", "published_at"],
  "warnings": ["Could not determine publish date from content"]
}
```

- `is_news: false` → show error to admin ("This does not look like AI/tech news: …")
- `missing_fields` → triggers the warning popup in Phase 3
- Fixed category list defined in code (e.g. models, research, policy, products, funding, open-source, other)
- Fallback JSON parser strips ``` fences if Claude ignores instructions
- Parse `published_at` with `python-dateutil`

**Exit criteria:** Shell test against a real article URL text and a JSON blob both return valid structured output.

---

## Phase 3 — Add News Admin (core feature)

**Goal:** Single admin page to add news from a link or pasted text.

### Input

One form with two modes (tabs or radio toggle):

| Mode | What admin provides | What the backend does |
|---|---|---|
| **Link** | A URL | `httpx` fetch → `newspaper3k` extract body (fallback: `readability-lxml`) → cap at 8000 chars |
| **Text** | Raw paste (plain, XML, JSON, HTML) | Use as-is, cap at 8000 chars |

### Flow

```
Admin submits URL or text
        ↓
Backend extracts/fetches content
        ↓
LLM extraction (Phase 2)
        ↓
   is_news?
   /        \
  no        yes
  ↓          ↓
Error     missing_fields or warnings?
message      /           \
           no            yes
            ↓              ↓
         Save Post    Warning popup
         → feed       (pre-filled form:
                       title, author, date,
                       category, tags, summary)
                            ↓
                      Admin edits + confirms
                            ↓
                         Save Post → feed
```

### Warning popup

When `missing_fields` is non-empty or `warnings` is non-empty:

- Show a modal (not a separate page) listing what is missing or uncertain
- Pre-fill all fields the LLM did extract
- Highlight empty/missing fields
- Admin can edit any field before confirming
- "Save anyway" creates the `Post` with `status=approved`
- "Cancel" discards — nothing saved

### Validation before save

- `title` and `summary` are required (admin must fill if LLM left them blank)
- `category` must be from the fixed list
- `tags` — admin can add custom tags in the popup

### UI

- Custom admin view at `/admin/add-news/` (not the default Django admin change form)
- Simple layout: input area, submit button, result area
- Bootstrap 5 for the modal
- After successful save, redirect to public feed or show "Added ✓" with link

**Exit criteria:** Admin can paste a URL or JSON/XML blob, see the warning popup when fields are missing, fill them in, and the post appears on the public feed.

---

## Phase 4 — Public Feed

**Goal:** Server-rendered feed of all approved posts.

### What to do

- `FeedView` — `Post` with `status=approved`, ordered by `published_at` desc (fallback: `created_at`), 20 per page
- Query params: `category`, `q` (search title + summary)
- Templates:
  - `base.html` — navbar, Bootstrap CDN
  - `feed.html` — search, category filter, post cards, pagination
  - `post_card.html` — title, summary, tags, date, "Read original →" link (only if `original_url` set)
- Served at `/`

**Exit criteria:** Feed loads, shows manually added posts, filtering and pagination work.

---

## Phase 5 — Deployment

**Goal:** Production on Fly.io.

### What to do

- `fly.toml` — `web` process only, 512MB, `DJANGO_SETTINGS_MODULE=production`
- Secrets: `DATABASE_URL`, `ANTHROPIC_API_KEY`, `SECRET_KEY`, `ALLOWED_HOSTS`
- After deploy: migrate, create superuser
- `fly deploy` for subsequent changes

**Exit criteria:** Public feed and add-news admin live at `https://your-app.fly.dev`.

---

## Phase Summary

| Phase | What it delivers |
|---|---|
| 0 | Deployable Django skeleton on Fly.io + Neon |
| 1 | `Post` model and migration |
| 2 | LLM extraction — validates news, returns structured fields + missing-field flags |
| 3 | **Add News admin** — URL or text input, warning popup for missing fields |
| 4 | Public feed |
| 5 | Production deployment |

---

## Build Order

```
Phase 0 → Phase 1 → Phase 2 → Phase 3 → Phase 4 → Phase 5
```

Phase 3 is the main deliverable. Everything else exists to support it.

---

## Architecture 2 (deferred — do not build now)

- `Source` model + admin for managing RSS/homepage sources
- Celery + Redis + Beat for scheduled fetching
- URL dedup via Redis
- Automated fetch pipeline (RSS + HTML scraper)
- Moderation queue (`pending` → approve/reject)
- Pre-seed 19 sources

---

## Key Design Decisions

- **Admin = add news only.** No source management, no bulk moderation, no fetch config in Architecture 1.
- **LLM is the gatekeeper.** Non-news input is rejected with a clear reason. Missing metadata triggers a popup, not a silent save.
- **URL and text are first-class inputs.** JSON/XML feeds pasted as text are valid — the LLM parses structure from raw content.
- **Posts go live immediately** after admin confirms in the popup. No pending queue for MVP.
- **No Source table yet.** Keeps the schema minimal. LLM infers context from content; admin can add a source label manually in the popup if needed later.
- **Single Fly process.** No worker machine until automated fetching ships.
- **Claude Haiku.** Fast and cheap for extraction. Upgrade to Sonnet only if quality is poor on specific input types.
