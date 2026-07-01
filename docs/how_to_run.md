# How to Run Rapid News and Scrutinize Locally

This guide details how to run the **Rapid News** (Django + Celery) project and the **Scrutinize** (FastAPI + Celery + Qdrant) RAG pipeline side-by-side on your local machine.

---

## ⚡ Conflict Resolution Overview

Running both projects locally creates two primary resource conflicts:
1. **HTTP Ports**: Both Django and FastAPI default to port `8000`.
2. **Redis Database**: Both projects default to using Redis database `0` (`redis://localhost:6379/0`), causing Celery task queue conflicts and cache overwrites.

### Resolution Strategy:
*   **Ports**:
    *   Run **Scrutinize** (RAG Service) on port `8000`.
    *   Run **Rapid News** on port `8050` (or another port of your choice).
*   **Redis Databases**:
    *   Use database `0` for **Scrutinize** (`redis://localhost:6379/0`).
    *   Use database `1` for **Rapid News** (ANTIX News) (`redis://localhost:6379/1`).

---

## 🚀 Step-by-Step Running Guide

### Step 1: Shared Services (Redis & Qdrant)

Only one Redis instance needs to be running. We will use the Docker Compose configuration from **Rapid News** to spin up Redis, and Scrutinize's configuration to spin up Qdrant.

1. **Start Redis** (from the `ai_news` directory):
   ```bash
   make docker-up
   ```
   *(This starts Redis on `localhost:6379`)*

2. **Start Qdrant** (from your `scrutinize` directory):
   ```bash
   make infra-qdrant
   ```
   *(This starts Qdrant on `localhost:6333`)*

---

### Step 2: Configure and Run Scrutinize (RAG pipeline)

1. Open the **Scrutinize** project folder.
2. Verify or create your `backend/.env` file. Ensure the following configurations:
   ```env
    # Use Redis Database 0 (Default)
    REDIS_URL=redis://localhost:6379/0
   
   # Qdrant local instance
   QDRANT_URL=http://localhost:6333
   
   # Neon PostgreSQL for Scrutinize Metadata/Logs
   DATABASE_URL=postgresql://... (Use your Scrutinize database)
   ```
3. Run the database migrations:
   ```bash
   make db-migrate
   ```
4. Start the Scrutinize FastAPI backend on port **`8000`**:
   ```bash
   # In Terminal 1 (Scrutinize Backend)
   cd backend
   uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
   ```
5. Start the Scrutinize Celery worker:
   ```bash
   # In Terminal 2 (Scrutinize Worker)
   cd backend
   celery -A app.workers.celery_app worker --loglevel=info --pool=solo
   ```
6. Start the Scrutinize React Frontend (if needed):
   ```bash
   # In Terminal 3 (Scrutinize Frontend)
   cd frontend
   npm run dev
   ```
   *(Defaults to `http://localhost:5173`)*

---

### Step 3: Configure and Run Rapid News

1. Open the **Rapid News** (`ai_news`) project folder.
2. Verify or create your `.env` file. Ensure the following configurations:
   ```env
   # Use Redis Database 1 to isolate from Scrutinize
   REDIS_URL=redis://localhost:6379/1
   
   # Neon PostgreSQL for Rapid News
   DATABASE_URL=postgresql://... (Use your Rapid News database)
   
   # Point to Scrutinize API running on port 8000
   SCRUTINIZE_API_BASE_URL=http://localhost:8000
   SCRUTINIZE_ADMIN_API_KEY=scrutinize_sk_d5e6feae8ca4ff07557f29e8536f20f89b60f73f40270b9e
   SCRUTINIZE_PUBLIC_CLIENT_KEY=scrutinize_pk_bad456b4ad1c215b093a78e12e33629074ee10f95e7e291b
   ```
3. Run Django migrations & seed default news sources:
   ```bash
   make migrate
   python manage.py seed_sources
   ```
4. Start the Rapid News backend on port **`8050`**:
   ```bash
   # In Terminal 4 (Rapid News Backend)
   python manage.py runserver 8050
   ```
   *(Your Django app is now running at `http://127.0.0.1:8050/`)*
5. Start the Rapid News Celery worker:
   ```bash
   # In Terminal 5 (Rapid News Worker)
   make worker
   ```

---

## 🔍 Verifying the Setup

1. **Scrutinize Health Check**:
   Open `http://localhost:8000/health` or run:
   ```bash
   curl http://localhost:8000/health
   ```
   It should return `{"status": "ok", ...}` showing Redis and Qdrant connections are active.

2. **Rapid News API Connection**:
   Start your Rapid News application, and when you navigate to your Rapid News frontend at `http://127.0.0.1:8050/`, verify that the system can query the local RAG pipeline at port `8000` without connection errors.
