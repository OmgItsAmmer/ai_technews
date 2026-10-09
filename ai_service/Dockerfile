# syntax=docker/dockerfile:1
FROM python:3.12-slim AS builder
ENV PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /build
COPY pyproject.toml ./
COPY antix_ai ./antix_ai
RUN pip install --prefix=/install .

FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 TIKTOKEN_CACHE_DIR=/opt/tiktoken
RUN apt-get update && apt-get install -y --no-install-recommends redis-server && rm -rf /var/lib/apt/lists/*
COPY --from=builder /install /usr/local
WORKDIR /app
COPY alembic.ini ./
COPY migrations ./migrations
# Pre-fetch the tokenizer so the container needs no egress for token counting (best effort).
RUN python -c "import tiktoken; tiktoken.get_encoding('cl100k_base')" || true
RUN useradd --create-home --uid 10001 app && chown -R app /app /opt/tiktoken 2>/dev/null || true
USER app
EXPOSE 8100
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8100/health', timeout=3).status==200 else 1)"
# Default: API. Worker: `antix-ai worker`. Migrations: `antix-ai migrate`.
CMD ["antix-ai", "serve", "--host", "0.0.0.0", "--port", "8100"]
