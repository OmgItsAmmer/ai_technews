# Initial Setup Runbook

Fresh-machine guide to run **Antix News** (Django feed + fetch pipeline) and **Scrutinize** (RAG for Ask AI) together locally.

---

## Prerequisites

Install on the new PC:

| Tool | Version | Used for |
|------|---------|----------|
| **Python** | 3.12+ | Antix News + Scrutinize backend |
| **Node.js + npm** | 18+ (LTS) | Scrutinize frontend (optional for Antix-only dev) |
| **Docker Desktop** | latest | Redis + Qdrant |
| **Make** | any | Shortcut commands from repo root |
| **Git** | any | Clone repos |

On Windows, run `make` from **Git Bash**, **WSL**, or any shell where `make` is on `PATH`.

---

## Repository layout

The root Makefile expects Scrutinize as a sibling folder inside the Antix repo:

```text
ai_news/
├── apps/                  # Antix News Django app
├── Scrutinize/            # Scrutinize RAG service (separate repo — clone here)
│   ├── backend/
│   ├── frontend/
│   └── docker-compose.yml
├── Makefile
├── .env.example
└── manage.py
```

Clone Antix News, then clone Scrutinize into `Scrutinize/`:

```bash
git clone <antix-news-repo-url> ai_news
cd ai_news
git clone <scrutinize-repo-url> Scrutinize
```

---

## Port & Redis layout (important)

Both apps share one Redis container but **must use different Redis DB numbers** and **different HTTP ports**:

| Service | URL | Redis DB |
|---------|-----|----------|
| Scrutinize API (RAG) | `http://localhost:8000` | `redis://localhost:6379/0` |
| Antix News (web UI) | `http://localhost:8050` | `redis://localhost:6379/1` |
| Scrutinize UI (optional) | `http://localhost:5173` | — |
| Qdrant (vectors) | `http://localhost:6333` | — |

---

## One-time setup

Run all commands from the **`ai_news/` repo root** unless noted.

### 1. Install Python dependencies

```bash
make install
make install-scrutinize
```

### 2. Configure Antix News (`.env`)

```bash
cp .env.example .env
```

Edit `.env` — minimum required:

```env
# Django
SECRET_KEY=<long-random-string>
DEBUG=True
ALLOWED_HOSTS=localhost,127.0.0.1

# Neon Postgres (Antix News database — pooled connection string)
DATABASE_URL=postgresql://USER:PASSWORD@ep-xxxx.neon.tech/neondb?sslmode=require

# Redis DB 1 — isolated from Scrutinize
REDIS_URL=redis://localhost:6379/1

# LLM for article extraction (OpenAI or compatible local endpoint)
OPENAI_BASE_URL=https://your-local-or-ngrok-host/v1
OPENAI_API_KEY=not-needed-if-local
LLM_MODEL=Qwen/Qwen3.5-4B

# Scrutinize connection (Ask AI + article embedding sync)
SCRUTINIZE_API_BASE_URL=http://localhost:8000
SCRUTINIZE_ADMIN_API_KEY=scrutinize_sk_d5e6feae8ca4ff07557f29e8536f20f89b60f73f40270b9e
SCRUTINIZE_PUBLIC_CLIENT_KEY=scrutinize_pk_bad456b4ad1c215b093a78e12e33629074ee10f95e7e291b

CRON_SECRET=<long-random-string>
DJANGO_SETTINGS_MODULE=config.settings.development
```

Use the default Scrutinize API keys above for local dev unless your Scrutinize project defines different keys.

### 3. Configure Scrutinize (`Scrutinize/backend/.env`)

Create `Scrutinize/backend/.env` (copy from Scrutinize’s own `.env.example` if present):

```env
# Neon Postgres (Scrutinize metadata — can be same Neon project, different DB)
DATABASE_URL=postgresql+psycopg://USER:PASSWORD@ep-xxxx.neon.tech/neondb?sslmode=require

# Redis DB 0 — Scrutinize Celery broker
REDIS_URL=redis://localhost:6379/0

# Local Qdrant (started via make docker-up)
QDRANT_URL=http://localhost:6333

# LLM for RAG search (local Ollama/vLLM via ngrok or cloud OpenAI)
LOCAL_LLM_BASE_URL=https://your-ngrok-host/api/generate
# Or cloud mode — see Scrutinize docs for USE_CLOUD_LLM / OPENAI_API_KEY

# Cloudinary (required for Scrutinize file uploads in full mode)
CLOUDINARY_CLOUD_NAME=...
CLOUDINARY_API_KEY=...
CLOUDINARY_API_SECRET=...
```

For **search-only** testing without running a Scrutinize worker, Scrutinize docs allow `CELERY_TASK_ALWAYS_EAGER=true` in `backend/.env`. For Antix **Fetch latest → embed articles**, you need the Scrutinize worker running.

### 4. Start infrastructure (Redis + Qdrant)

```bash
make docker-up
```

Verify containers are up:

```bash
docker compose -f Scrutinize/docker-compose.yml ps
```

### 5. Apply database migrations

```bash
make scrutinize-migrate
make migrate
python manage.py seed_sources
make admin-user
```

`make admin-user` reads `ADMIN_USERNAME` and `ADMIN_PASSWORD` from `.env`, creates the admin account, and stores a **PBKDF2 hash** of the password in the database (never plaintext).

Alternatively, create an account interactively:

```bash
make superuser
```

`seed_sources` loads the default news sources. `make superuser` creates the Django admin account for `/admin`.

---

## Run the stack (5 terminals)

Start these in separate terminals from `ai_news/`:

| Terminal | Command | Purpose |
|----------|---------|---------|
| **1** | `make scrutinize-backend` | Scrutinize FastAPI on `:8000` (RAG API) |
| **2** | `make scrutinize-worker` | Embeds uploaded articles into Qdrant |
| **3** | `make backend` | Antix News UI + API on `:8050` |
| **4** | `make worker` | RSS fetch, LLM extraction, Scrutinize sync |
| **5** *(optional)* | `make scrutinize-frontend` | Scrutinize admin UI on `:5173` |

Antix News does **not** need terminal 5 — Ask AI is built into the Antix frontend at `http://127.0.0.1:8050/`.

---

## Verify everything works

### Scrutinize health

```bash
make scrutinize-health
# or
curl http://localhost:8000/health
```

Expect a JSON response with Redis and Qdrant reachable.

### Antix News UI

Open **http://127.0.0.1:8050/** — feed should load after fetch.

### End-to-end RAG (Ask AI)

1. Ensure terminals 1–4 are running.
2. In the Antix UI, click **Fetch latest** — this fetches articles, syncs them to Scrutinize, and queues embedding.
3. Wait for the embedding toast to finish.
4. Click **Ask AI** and send a question about recent news.

Manual sync (without full fetch):

```bash
python manage.py sync_scrutinize
```

---

## Quick reference — Makefile commands

```bash
# Infrastructure
make docker-up              # Start Redis (6379) + Qdrant (6333)
make docker-down            # Stop infrastructure

# Antix News
make install                # pip install requirements
make migrate                # Django migrations
make backend                # runserver :8050
make worker                 # Celery worker (fetch + sync)
make superuser              # Django admin user
make test                   # pytest

# Scrutinize
make install-scrutinize     # pip + npm install
make scrutinize-migrate     # Scrutinize DB migrations
make scrutinize-backend     # FastAPI :8000
make scrutinize-worker      # Celery worker (embedding)
make scrutinize-frontend    # Vite :5173
make scrutinize-health      # LLM / API health check
make check-qdrant           # Print Scrutinize config + Qdrant URL
```

---

## Troubleshooting

| Problem | Check |
|---------|--------|
| Ask AI returns errors | Scrutinize backend running on `:8000`? `SCRUTINIZE_*` keys in Antix `.env`? |
| Fetch completes but Ask AI has no context | Scrutinize worker running? Run `python manage.py sync_scrutinize` and watch worker logs. |
| Celery tasks never run | Redis up? Antix uses DB `1`, Scrutinize uses DB `0`. |
| Port already in use | Only one process on `:8000` (Scrutinize) and one on `:8050` (Antix). |
| Qdrant errors after upgrade | From `Scrutinize/`: `make reset-qdrant` then `make docker-up` (wipes vector data). |

---

## Related docs

- [How to run Antix + Scrutinize side by side](../how_to_run.md)
- [Scrutinize architecture & env vars](../rag_context.md)
- [Scrutinize API reference](../architecture/api_reference.md)
