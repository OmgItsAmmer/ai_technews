# Initial Setup Runbook

Welcome to the **AI News** project! This guide covers the steps to get the backend, frontend, and background workers running locally on your machine.

## Prerequisites

- **Python 3.12+**
- **Docker** & **Docker Compose** (for Redis)
- **Make** (for using the provided Makefile commands)

## Setup Instructions

### 1. Install Dependencies
Install all required Python packages using pip (via the Makefile):

```bash
make install
```

### 2. Environment Configuration
Copy the sample environment file to create your local `.env`:

```bash
cp .env.example .env
```

Open `.env` and configure the necessary variables. Ensure you provide:
- `DATABASE_URL`: Connection string for PostgreSQL (or SQLite for local quick start if supported).
- `OPENAI_BASE_URL`: The ngrok URL (or local URL) for your local LLM (e.g., `https://19d9-154-192-5-123.ngrok-free.app/v1/chat/completions`).
- `LLM_MODEL`: The local model name (e.g., `QWEN/QWEN3.5:4b`).

### 3. Start Redis Services
The background tasks (Celery) and caching require Redis. Start it using Docker:

```bash
make docker-up
```

### 4. Database Migrations
Apply the initial Django migrations to set up your database schema:

```bash
make migrate
```

*(Optional)* Create a superuser account to access the Django admin panel (`/admin`):

```bash
make superuser
```

### 5. Running the Application

To fully test the system, you'll need the web server running alongside the background workers.

**Start the Web Server:**
This serves both the Django backend APIs and the Jinja2 frontend application at `http://127.0.0.1:8000/`.

```bash
make backend
```
*(Note: `make frontend` is an alias to `make backend` since they are served together).*

**Start the Celery Worker (in a separate terminal):**
This processes background tasks like fetching RSS feeds and extracting data via the LLM.

```bash
make worker
```


## Useful Development Commands

- **Run tests:** `make test` (runs all tests including integrations) or `make test-ci` (runs unit tests on SQLite).
- **Stop Docker services:** `make docker-down`
- **Clean cache files:** `make clean`
