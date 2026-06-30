# How to Run ANTIX News Locally

This guide explains the system prerequisites and the exact commands required to get the **ANTIX News** backend, database, queue, and frontend services up and running on your local machine.

---

## 📋 Prerequisites

Ensure you have the following installed on your system before proceeding:

1. **Python (version 3.12 or newer)**: For running the Django application and Celery workers.
2. **Docker & Docker Compose**: Required to run the Redis container (used as the Celery message broker and deduplication store).
3. **Make**: Command-line utility to run automated tasks via the `Makefile`.

---

## 🛠️ Step-by-Step Execution Guide

### 1. Installation & Environment Setup
First, install the Python package dependencies and prepare your environment settings:

```bash
# Install Python packages
make install

# Copy the environment template
cp .env.example .env
```
> [!IMPORTANT]
> Open the `.env` file and configure your credentials:
> * Make sure `DATABASE_URL` points to your Neon PostgreSQL or local PostgreSQL database.
> * Ensure `OPENAI_BASE_URL` and `LLM_MODEL` are correctly configured (without trailing/double slashes) to connect to your LLM API.

---

### 2. Start Redis (Docker)
Start the local Redis server container in the background:
```bash
make docker-up
```

---

### 3. Database Initialization & Seeding
Prepare the database schema, seed standard news sources, and create an admin user:

```bash
# Run database migrations
make migrate

# Seed standard technology/AI news feeds
python manage.py seed_sources

# Create an administrator account
make superuser
```

---

### 4. Running the Application Services
You must run both the Django web server and the Celery worker concurrently. Open two separate terminal windows:

#### Terminal 1: Start Django Web Server
Runs the web dashboard, admin panel, and JSON endpoints:
```bash
make backend
```
* Access the main feed at: [http://127.0.0.1:8000/](http://127.0.0.1:8000/)
* Access the admin verification panel at: [http://127.0.0.1:8000/admin/](http://127.0.0.1:8000/admin/)

#### Terminal 2: Start Celery Worker
Processes the background scraping, deduplication, and LLM text extraction tasks:
```bash
make worker
```

---

## 🔍 Verifying the Setup
1. Open [http://127.0.0.1:8000/](http://127.0.0.1:8000/) in your web browser.
2. Click the **Fetch** button.
3. Observe the logs in your **Celery worker terminal** (Terminal 2) to see active feeds being parsed and analyzed in real-time.
