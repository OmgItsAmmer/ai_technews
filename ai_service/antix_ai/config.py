"""Service configuration.

All settings come from the environment (prefix ``AI_``) or ``ai_service/.env``.
Secrets have no defaults: the service refuses to start without them.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import BaseModel, Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

ProviderKind = Literal["openai", "anthropic", "offline"]
RerankKind = Literal["none", "http", "llm"]


class ModelRole(BaseModel):
    """One model role. Set via AI_FAST__MODEL, AI_STRONG__BASE_URL, ..."""

    provider: ProviderKind = "openai"
    model: str = "gpt-4o-mini"
    base_url: str | None = None
    api_key: SecretStr | None = None
    timeout_s: float = 60.0
    max_retries: int = 2
    temperature: float = 0.1
    # Qwen3-style reasoning models: ask the server to skip <think> blocks (vLLM/SGLang)
    disable_thinking: bool = False


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="AI_",
        env_file=".env",
        env_file_encoding="utf-8",
        env_nested_delimiter="__",
        extra="ignore",
    )

    env: Literal["dev", "test", "prod"] = "dev"
    log_level: str = "INFO"
    log_json: bool = True

    # Infrastructure
    database_url: str
    redis_url: str = "redis://localhost:6379/2"
    db_pool_min: int = 1
    db_pool_max: int = 10
    # Django-owned tables (read-only for this service)
    posts_table: str = "public.posts_post"
    sources_table: str = "public.sources_source"
    keywords_table: str = "public.posts_keywordsetting"

    # Auth: Django -> service
    service_key: SecretStr

    # Models
    fast: ModelRole = Field(default_factory=ModelRole)
    strong: ModelRole = Field(default_factory=lambda: ModelRole(model="gpt-4o"))
    # Fallback for the strong role when it fails (e.g. local model offline)
    strong_fallback: ModelRole | None = None

    embed_provider: Literal["openai", "offline"] = "openai"
    embed_model: str = "text-embedding-3-small"
    embed_dim: int = 1536
    embed_base_url: str | None = None
    embed_api_key: SecretStr | None = None
    embed_batch_size: int = 64

    rerank: RerankKind = "llm"
    rerank_url: str | None = None  # TEI / Cohere / Jina compatible /rerank endpoint
    rerank_api_key: SecretStr | None = None
    rerank_model: str | None = None

    # Retrieval
    retrieval_candidates: int = 50
    rerank_candidates: int = 30
    evidence_articles: int = 8
    max_chunks_per_article: int = 2
    max_articles_per_story: int = 2
    hnsw_ef_search: int = 80

    # Context
    evidence_token_budget: int = 6000
    history_turns: int = 6
    default_timezone: str = "UTC"

    # Ingestion
    chunk_target_tokens: int = 420
    chunk_overlap_tokens: int = 60
    enrich_with_llm: bool = True
    story_window_hours: int = 72
    story_similarity: float = 0.82
    story_entity_floor: float = 0.55
    backfill_days: int = 90

    # Verification
    verify_with_llm: bool = True
    min_grounding: float = 0.6

    # Caching (seconds)
    cache_embed_ttl: int = 86_400
    cache_plan_ttl: int = 3_600
    cache_answer_ttl: int = 900

    # Rate limiting (per session, per minute)
    rate_limit_per_minute: int = 30

    @model_validator(mode="after")
    def _check(self) -> Settings:
        if self.env == "prod" and len(self.service_key.get_secret_value()) < 24:
            raise ValueError("AI_SERVICE_KEY must be at least 24 chars in prod")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
