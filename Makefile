# Makefile for the AI News app (Django) and its Antix AI service (ai_service/).
# Supports Django, Celery, the AI service (FastAPI + worker), Docker infra, evals and utility tasks.

.PHONY: help install docker-up up docker-down dev migrate makemigrations backend frontend worker shell superuser admin-user \
	test test-ci clean \
	ai-setup ai-install ai-up ai-down ai-migrate ai-serve ai-worker ai-backfill ai-reconcile ai-ask ai-health ai-stats \
	ai-test ai-lint ai-evals ai-eval ai-bench ai-docker-build

# Default command: display help
help:
	@echo "======================================================================"
	@echo "AI News + Antix AI service"
	@echo "======================================================================"
	@echo "Infrastructure (Docker):"
	@echo "  make docker-up            - Start Django's Redis AND the AI service's Postgres+Redis"
	@echo "  make docker-down          - Stop both"
	@echo ""
	@echo "AI News (Django app):"
	@echo "  make dev                  - Run Django app and AI service concurrently with colored logs"
	@echo "  make install              - Install Django Python requirements"
	@echo "  make migrate              - Apply Django database migrations"
	@echo "  make makemigrations       - Generate new Django database migrations"
	@echo "  make backend              - Run Django development server (port 8050)"
	@echo "  make worker               - Start the Django Celery worker process"
	@echo "  make shell                - Open the Django Python shell"
	@echo "  make superuser            - Create a Django admin superuser"
	@echo ""
	@echo "Antix AI service (ai_service/, port 8100):"
	@echo "  make ai-setup             - Generate ai_service/.env and wire Django .env (AI_BACKEND=antix)"
	@echo "  make ai-install           - Create ai_service venv and install dependencies"
	@echo "  make ai-migrate           - Apply AI schema migrations (schema 'ai')"
	@echo "  make ai-serve             - Run the AI API with reload"
	@echo "  make ai-worker            - Run the AI background worker (indexing)"
	@echo "  make ai-backfill          - Index/refresh approved posts (DAYS=90, FORCE=1 to re-embed)"
	@echo "  make ai-reconcile         - Ask the running service to reconcile its index"
	@echo "  make ai-ask Q=\"...\"       - Ask a question from the terminal"
	@echo "  make ai-health            - Check /ready of the running service"
	@echo "  make ai-stats             - Show index size and unindexed posts"
	@echo "  make ai-evals / ai-eval   - Generate golden set / run evals (BACKEND=antix|scrutinize)"
	@echo "  make ai-bench             - Latency benchmark against the running service"
	@echo "  make ai-test / ai-lint    - Service tests / lint"
	@echo "  make ai-docker-build      - Build the AI service container image"
	@echo ""
	@echo "Testing & Quality:"
	@echo "  make test                 - Run the Django pytest suite"
	@echo "  make test-ci              - Run Django unit tests mimicking CI"
	@echo "  make clean                - Remove Python cache files"
	@echo "======================================================================"

AI_URL ?= http://localhost:8100
AI_PY  ?= python

# --- Installation & Setup ---
install:
	pip install -r requirements.txt

# --- Infrastructure ---
# Django's Redis (docker-compose.yml, port 6380) + AI service Postgres/pgvector (55432) and Redis (6381).
docker-up:
	docker compose up -d
	docker compose -f ai_service/docker-compose.yml up -d db redis

up: docker-up

docker-down:
	docker compose down
	docker compose -f ai_service/docker-compose.yml down

# --- AI News (Django) Targets ---
migrate:
	python manage.py migrate

makemigrations:
	python manage.py makemigrations

backend:
	python manage.py runserver 8050

dev: docker-up
	python scripts/run_all.py

frontend: backend

shell:
	python manage.py shell

superuser:
	python manage.py createsuperuser

admin-user:
	python manage.py ensure_admin_user

worker:
	celery -A config worker --pool=solo --loglevel=info

test:
	pytest

test-ci: export DATABASE_URL = sqlite:///:memory:
test-ci:
	pytest -m "not integration"

# --- Antix AI service (ai_service/) ---
# Configure ai_service/.env first (see ai_service/.env.example). Django needs
# AI_BACKEND=antix, AI_SERVICE_URL and AI_SERVICE_KEY (see .env.example).
ai-setup:
	python ai_service/scripts/init_env.py

ai-install:
	cd ai_service && python -m venv .venv
	cd ai_service && (.venv/Scripts/python -m pip install -e ".[dev]" || .venv/bin/python -m pip install -e ".[dev]")

ai-up: docker-up

ai-down: docker-down

ai-migrate:
	cd ai_service && $(AI_PY) -m antix_ai.cli migrate

ai-serve:
	cd ai_service && $(AI_PY) -m antix_ai.cli serve --port 8100 --reload

ai-worker:
	cd ai_service && $(AI_PY) -m antix_ai.cli worker

ai-backfill:
	cd ai_service && $(AI_PY) -m antix_ai.cli backfill $(if $(DAYS),--days $(DAYS),) $(if $(FORCE),--force,)

ai-reconcile:
	curl -s -X POST $(AI_URL)/v1/ingest/reconcile -H "X-Service-Key: $$AI_SERVICE_KEY" -H "Content-Type: application/json" -d "{}"

ai-ask:
	cd ai_service && $(AI_PY) -m antix_ai.cli ask "$(Q)"

ai-health:
	curl -s $(AI_URL)/ready

ai-stats:
	curl -s $(AI_URL)/v1/admin/stats -H "X-Service-Key: $$AI_SERVICE_KEY"

ai-test:
	cd ai_service && $(AI_PY) -m pytest -q

ai-lint:
	cd ai_service && $(AI_PY) -m ruff check antix_ai tests migrations scripts

ai-evals:
	cd ai_service && $(AI_PY) -m antix_ai.cli gen-evals --out evals/datasets/golden.jsonl --n 150

ai-eval:
	cd ai_service && $(AI_PY) -m antix_ai.cli eval --backend $(or $(BACKEND),antix) --dataset evals/datasets/golden.jsonl

ai-bench:
	cd ai_service && $(AI_PY) scripts/bench.py --url $(AI_URL) --key "$$AI_SERVICE_KEY"

ai-docker-build:
	docker build -t antix-ai ai_service

# --- Utilities ---
clean:
	@if exist .pytest_cache rmdir /s /q .pytest_cache
	@for /d /r . %%d in (__pycache__) do @if exist "%%d" rmdir /s /q "%%d"
	@echo "Cleaned __pycache__ and test caches."
