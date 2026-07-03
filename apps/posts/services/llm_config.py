"""Resolve LLM URL and model from admin config with .env fallback."""

from django.conf import settings


def get_effective_llm_settings() -> tuple[str | None, str]:
    """
    Return (base_url, model_name).
    Admin LLMConfig values override environment when non-empty.
    """
    from apps.posts.models import LLMConfig

    base_url = settings.OPENAI_BASE_URL or None
    model_name = settings.LLM_MODEL

    row = LLMConfig.objects.first()
    if row:
        if row.base_url.strip():
            base_url = row.base_url.strip()
        if row.model_name.strip():
            model_name = row.model_name.strip()

    return base_url, model_name


def get_effective_api_key() -> str:
    return settings.OPENAI_API_KEY or "not-needed"
