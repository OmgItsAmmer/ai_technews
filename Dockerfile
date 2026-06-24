FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DJANGO_SETTINGS_MODULE=config.settings.production

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq-dev \
    gcc \
    curl \
    redis-server \
    supervisor \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN SECRET_KEY=build-only \
    DATABASE_URL=postgresql://build:build@localhost:5432/build \
    python manage.py collectstatic --noinput

COPY deploy/supervisord.conf /etc/supervisor/conf.d/supervisord.conf

EXPOSE 8000

CMD ["supervisord", "-c", "/etc/supervisor/conf.d/supervisord.conf"]
