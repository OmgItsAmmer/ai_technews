# Rapid News 🚀

Rapid News is a state-of-the-art tech and AI news aggregator. It features a modern, high-performance client-side feed with smooth animations, search and tag filtering, and a custom admin intake dashboard powered by a local Large Language Model (LLM) parsing pipeline.

---

## Key Features

*   **Jinja2 & DTL Multi-Engine Rendering**: Offers a dual-engine architecture:
    *   **Client-Side Frontend**: Handled via `django-jinja` using Jinja2 templates (`.jinja`) for responsive rendering, instant state filtering, and bookmarks.
    *   **Admin-Side Dashboard**: Handled via standard Django templates (`.html`) to support built-in Django admin views alongside custom tools.
*   **AI-Powered Parsing Pipeline**: Integrates with a local LLM (Qwen/OpenAI compatible API) to automatically extract article titles, authors, publication dates, summaries, and tags from raw text or homepage scrapers.
*   **Admin Intake Dashboard**: A custom admin workspace (`/admin/`) allowing administrators to input articles by pasting raw text or feeding a URL, preview the real-time LLM-extracted metadata, modify fields, and publish them directly to the main feed.
*   **Asynchronous Background Fetching**: Uses Celery (with Redis broker) to run cron-like tasks fetching from 19 tech sources (both RSS and webpage discovery scrapers) concurrently.
*   **Deduplication & Caching**: Employs Redis cache storage to track seen URLs with a 30-day TTL, preventing duplicate fetches and optimizing bandwidth.
*   **Premium Visual Experience**:
    *   Sleek dark-mode interface with harmony-driven color palettes.
    *   Floating glassmorphism header navigation bar.
    *   Smooth fade-in/fade-out scroll animations.
    *   Real-time search and filter updates (AJAX) on both the main feed and saved bookmark pages.

---

## Technology Stack

*   **Backend**: Django 5.2 (Python 3.12+)
*   **Task Queue**: Celery (using Redis as broker & backend)
*   **Database**: Neon PostgreSQL
*   **Caching/Deduplication**: Redis Cache
*   **AI Integration**: OpenAI SDK (pointing to local/remote LLM endpoint)
*   **Frontend Logic**: Vanilla JavaScript (AJAX, DOM manipulation, IntersectionObserver)
*   **Styles**: Custom Vanilla CSS (no Tailwind, custom layout variables)

---

## Getting Started

### 1. Install Dependencies
Make sure you have Python 3.12+ and pip installed. Run:
```bash
make install
```

### 2. Environment Configuration
Create a local `.env` file in the root of the directory:
```bash
cp .env.example .env
```
Ensure the following variables are configured:
*   `DATABASE_URL`: Your Neon PostgreSQL database pooled connection string.
*   `REDIS_URL`: URL pointing to your local/production Redis instance (e.g. `redis://localhost:6379/0`).
*   `OPENAI_BASE_URL`: The local LLM endpoint (e.g. ngrok endpoint or local host URL).
*   `LLM_MODEL`: Model name (e.g., `Qwen/Qwen3.5-4B`).
*   `CRON_SECRET`: Secret token used by external triggers (like GitHub Actions) to authenticate scheduled fetches.

### 3. Start Redis Container
Ensure Docker is running, then run the Redis container:
```bash
make docker-up
```

### 4. Database Setup & Migrations
Apply migrations to prepare the database schema:
```bash
make migrate
```
*(Optional)* Create an admin superuser account:
```bash
make superuser
```

---

## Running the Application

Both the client frontend and custom admin dashboard run under the same Django instance. Open separate terminal windows and run:

### Start the Web Application
```bash
make backend
```
*   **Client Feed**: Accessible at `http://127.0.0.1:8000/`
*   **Admin Dashboard**: Accessible at `http://127.0.0.1:8000/admin/`

### Start the Celery Worker
```bash
make worker
```

---

## Testing & Quality

We use `pytest` for the unit and integration test suite.
To prevent Neon PostgreSQL database locks caused by active worker/server connections, `pytest` is configured via `pytest.ini` to reuse the test database (`--reuse-db`).

Run all tests:
```bash
make test
```

Run SQLite-based unit tests (CI fallback):
```bash
make test-ci
```

---

## Scheduled Background Fetching
The project includes a GitHub Actions scheduled workflow (`.github/workflows/trigger-fetch.yml`) configured to hit the `/internal/trigger-fetch/` endpoint every **45 minutes**.

> [!IMPORTANT]
> Because GitHub Actions only registers scheduled triggers on the default branch of a repository, the workflow file must be pushed/merged onto the default branch (usually `main` or `master`) to activate.
