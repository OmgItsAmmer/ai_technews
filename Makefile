# Makefile for AI News and Scrutinize projects
# Supports backend (Django), Scrutinize (FastAPI, React/Vite), Docker (Redis, Qdrant), Celery, and utility tasks.

.PHONY: help install install-scrutinize docker-up docker-down migrate makemigrations backend frontend worker beat shell superuser test test-ci clean \
	scrutinize-backend scrutinize-frontend scrutinize-worker scrutinize-migrate scrutinize-health check-qdrant

# Default command: display help
help:
	@echo "======================================================================"
	@echo "AI News & Scrutinize Project Management Commands"
	@echo "======================================================================"
	@echo "Infrastructure (Docker):"
	@echo "  make docker-up            - Start Redis (6379) and Qdrant (6333) containers"
	@echo "  make docker-down          - Stop and remove infrastructure containers"
	@echo ""
	@echo "AI News (Django app):"
	@echo "  make install              - Install Django Python requirements"
	@echo "  make migrate              - Apply Django database migrations"
	@echo "  make makemigrations       - Generate new Django database migrations"
	@echo "  make backend              - Run Django development server (port 8050)"
	@echo "  make worker               - Start the Django Celery worker process"
	@echo "  make shell                - Open the Django Python shell"
	@echo "  make superuser            - Create a Django admin superuser"
	@echo ""
	@echo "Scrutinize (FastAPI + React/Vite app):"
	@echo "  make install-scrutinize   - Install Scrutinize backend & frontend dependencies"
	@echo "  make scrutinize-migrate   - Apply Scrutinize (FastAPI) database migrations"
	@echo "  make scrutinize-backend   - Run Scrutinize FastAPI dev server (port 8000)"
	@echo "  make scrutinize-frontend  - Run Scrutinize Vite frontend server (port 5173)"
	@echo "  make scrutinize-worker    - Run Scrutinize Celery worker process"
	@echo "  make scrutinize-health    - Check Scrutinize local LLM health"
	@echo ""
	@echo "Testing & Quality:"
	@echo "  make test                 - Run the Django pytest suite"
	@echo "  make test-ci              - Run Django unit tests mimicking CI"
	@echo "  make clean                - Remove Python cache files"
	@echo "======================================================================"

# --- Installation & Setup ---
install:
	pip install -r requirements.txt

install-scrutinize:
	cd Scrutinize/backend && pip install -e ".[dev]"
	cd Scrutinize/frontend && npm install

# --- Infrastructure ---
# Runs Redis (6379) and Qdrant (6333) using the Scrutinize compose config.
# Both apps share the Redis instance on 6379 but use different databases (DB 0 for Scrutinize, DB 1 for AI News).
docker-up:
	docker compose -f Scrutinize/docker-compose.yml up -d qdrant redis

up: docker-up

docker-down:
	docker compose -f Scrutinize/docker-compose.yml down

# --- AI News (Django) Targets ---
migrate:
	python manage.py migrate

makemigrations:
	python manage.py makemigrations

backend:
	python manage.py runserver 8050

frontend: backend

shell:
	python manage.py shell

superuser:
	python manage.py createsuperuser

worker:
	celery -A config worker --pool=solo --loglevel=info

test:
	pytest

test-ci: export DATABASE_URL = sqlite:///:memory:
test-ci:
	pytest -m "not integration"

# --- Scrutinize Targets ---
scrutinize-migrate:
	cd Scrutinize/backend && python scripts/apply_migrations.py

scrutinize-backend:
	cd Scrutinize/backend && uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

scrutinize-frontend:
	cd Scrutinize/frontend && npm run dev

scrutinize-worker:
	cd Scrutinize/backend && celery -A app.workers.celery_app worker --loglevel=info --pool=solo

scrutinize-health:
	curl -s http://localhost:8000/v2/llm-health

check-qdrant:
	cd Scrutinize/backend && python scripts/print_config.py

# --- Utilities ---
clean:
	@if exist .pytest_cache rmdir /s /q .pytest_cache
	@for /d /r . %%d in (__pycache__) do @if exist "%%d" rmdir /s /q "%%d"
	@echo "Cleaned __pycache__ and test caches."

