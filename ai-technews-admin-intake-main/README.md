# AI Tech News – Admin Intake (Phase 4)

A Django 5 admin panel for ingesting and publishing AI/tech news posts, backed by PostgreSQL with AI-powered metadata extraction via OpenAI.

## Features

- **URL Mode** – paste an article URL; the backend scrapes it with `newspaper3k` (readability fallback) and sends it to GPT-4o-mini for structured extraction
- **Text Mode** – paste raw prose, XML (RSS `<item>`), or JSON; same AI pipeline applies
- **Missing-field resolution** – if the AI cannot determine author, date, or tags a native `<dialog>` modal prompts you to fill them in before publishing
- **Duplicate detection** – publishing the same URL twice returns a `409 Conflict` with a link to the existing post
- **Read-only audit list** – `/admin/posts/post/` shows all published posts; no editing allowed through the admin
- **Mock mode** – no OpenAI key? The service returns deterministic fake responses so you can develop without spending credits

## Tech stack

| Layer | Choice |
|---|---|
| Framework | Django 5.2 |
| Database | PostgreSQL 16 (GIN index on `tags` JSONField) |
| Templates | Jinja2 via `django-jinja` |
| Scraping | `newspaper3k` → `readability-lxml` fallback |
| AI | OpenAI `gpt-4o-mini` |
| Styling | Vanilla CSS (Bebas Neue + DM Sans, dark mode) |
| Frontend | Vanilla JS + native `<dialog>` |

## Quick start

```bash
# 1. Clone the repo
git clone https://github.com/saad-faran/ai-technews-admin-intake.git
cd ai-technews-admin-intake

# 2. Copy and configure environment
cp .env.example .env
# Edit .env — set DATABASE_URL and OPENAI_API_KEY

# 3. Start PostgreSQL (macOS via Homebrew)
brew services start postgresql@16
createdb technews_admin          # or use your own DATABASE_URL

# 4. Create and activate virtual environment
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# 5. Run migrations
python manage.py migrate

# 6. Create a superuser
python manage.py createsuperuser

# 7. Start the development server
python manage.py runserver
```

Visit **http://127.0.0.1:8000/admin/** and log in.

## Environment variables

| Variable | Description | Example |
|---|---|---|
| `SECRET_KEY` | Django secret key | `django-insecure-...` |
| `DEBUG` | Enable debug mode | `True` |
| `DATABASE_URL` | PostgreSQL connection string | `postgres://user:pass@localhost:5432/technews_admin` |
| `OPENAI_API_KEY` | OpenAI API key (use `sk-mock-...` to enable mock mode) | `sk-...` |
| `OPENAI_MODEL` | Model to use | `gpt-4o-mini` |
| `ALLOWED_HOSTS` | Comma-separated allowed hosts | `localhost,127.0.0.1` |

## Running tests

```bash
# Unit + integration tests
python manage.py test

# End-to-end scenario matrix (requires running dev server)
python scratch/test_matrix.py
```

## Project structure

```
.
├── apps/
│   ├── extraction/     # Scraper, OpenAI client, prompt, validators, service
│   └── posts/          # Post model, views, admin, tests, constants
├── config/             # settings.py, urls.py, custom AdminSite
├── static/             # CSS + JS assets
├── templates/          # base.html + admin/add_news_index.html
├── .env.example        # Environment template
├── docker-compose.yml  # PostgreSQL 16 via Docker
└── requirements.txt
```
