import pytest

from apps.posts.models import LLMConfig
from apps.posts.services.llm_config import get_effective_llm_settings


@pytest.mark.django_db
def test_llm_config_falls_back_to_settings(settings):
    settings.LOCAL_LLM_BASE_URL = "https://env.example/v1"
    settings.LOCAL_LLM_MODEL = "env-model"

    base_url, model = get_effective_llm_settings()
    assert base_url == "https://env.example/v1"
    assert model == "env-model"


@pytest.mark.django_db
def test_llm_config_db_overrides_settings(settings):
    settings.LOCAL_LLM_BASE_URL = "https://env.example/v1"
    settings.LOCAL_LLM_MODEL = "env-model"

    LLMConfig.objects.create(
        base_url="http://localhost:11434/v1",
        model_name="Qwen/Qwen3.5-4B",
    )

    base_url, model = get_effective_llm_settings()
    assert base_url == "http://localhost:11434/v1"
    assert model == "Qwen/Qwen3.5-4B"


@pytest.mark.django_db
def test_llm_config_partial_override(settings):
    settings.LOCAL_LLM_BASE_URL = "https://env.example/v1"
    settings.LOCAL_LLM_MODEL = "env-model"

    LLMConfig.objects.create(base_url="", model_name="admin-model-only")

    base_url, model = get_effective_llm_settings()
    assert base_url == "https://env.example/v1"
    assert model == "admin-model-only"
