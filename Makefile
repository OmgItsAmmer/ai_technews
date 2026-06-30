# Makefile for AI News project
# Supports backend (Django), frontend (Django templates/views), Docker (Redis), Celery, and utility tasks.

.PHONY: help install docker-up docker-down migrate makemigrations backend frontend worker beat shell superuser test test-ci clean

# Default command: display help
help:
	@echo "======================================================================"
	@echo "AI News Project Management Commands"
	@echo "======================================================================"
	@echo "Development Server:"
	@echo "  make backend         - Run the Django backend development server"
	@echo "  make frontend        - Run the frontend (alias to backend server)"
	@echo "  make shell           - Open the Django python shell"
	@echo "  make superuser       - Create a Django admin superuser"
	@echo ""
	@echo "Database & Migrations:"
	@echo "  make migrate         - Apply database migrations"
	@echo "  make makemigrations  - Generate new database migrations"
	@echo ""
	@echo "Docker Services:"
	@echo "  make docker-up       - Start Docker services (e.g., Redis) in background"
	@echo "  make docker-down     - Stop Docker services"
	@echo ""
	@echo "Celery Tasks:"
	@echo "  make worker          - Start the Celery worker process"
	@echo ""
	@echo "Testing & Quality:"
	@echo "  make test            - Run the pytest suite"
	@echo "  make test-ci         - Run only unit tests with SQLite (mimicking CI)"
	@echo "  make clean           - Remove python cache and test cache files"
	@echo ""
	@echo "Setup:"
	@echo "  make install         - Install python dependencies from requirements.txt"
	@echo "======================================================================"

# Install Python requirements
install:
	pip install -r requirements.txt

# Run Docker dependencies (e.g., Redis)
docker-up:
	docker-compose up -d

up: docker-up

# Stop Docker containers
docker-down:
	docker-compose down

# Apply Django migrations
migrate:
	python manage.py migrate

# Create new Django migrations
makemigrations:
	python manage.py makemigrations

# Run Django development server (backend)
backend:
	python manage.py runserver

# Run Django development server (frontend - since frontend is a Django app)
frontend: backend

# Start Django python shell
shell:
	python manage.py shell

# Create superuser
superuser:
	python manage.py createsuperuser

# Start Celery worker
worker:
	celery -A config worker --pool=solo --loglevel=info


# Run test suite
test:
	pytest

# Run test suite mimicking the CI/CD pipeline (using in-memory SQLite, skipping integration tests)
test-ci: export DATABASE_URL = sqlite:///:memory:
test-ci:
	pytest -m "not integration"

# Clean up Python cache, build files, and testing cache
clean:
	@if exist .pytest_cache rmdir /s /q .pytest_cache
	@for /d /r . %%d in (__pycache__) do @if exist "%%d" rmdir /s /q "%%d"
	@echo "Cleaned __pycache__ and test caches."
