from unittest.mock import MagicMock, patch

from apps.extractor.service import _normalize_tags, _parse_json_response, extract_from_text


def test_parse_json_response_strips_markdown_fences():
    raw = '```json\n{"is_valid_news": true, "title": "Hi"}\n```'
    data = _parse_json_response(raw)
    assert data["title"] == "Hi"


def test_normalize_tags_strips_invalid_slugs():
    tags, missing = _normalize_tags(["llms", "not-a-real-tag"])
    assert tags == ["llms"]
    assert missing == []


def test_normalize_tags_flags_missing_when_empty():
    tags, missing = _normalize_tags(["bad-slug"])
    assert tags == []
    assert missing == ["tags"]


@patch("apps.extractor.service.get_effective_llm_settings")
@patch("apps.extractor.service._build_client")
def test_extract_from_text_returns_structured_metadata(mock_build_client, mock_get_llm_settings):
    mock_get_llm_settings.return_value = ("http://mock-url/v1", "mock-model")
    mock_client = MagicMock()
    mock_build_client.return_value = mock_client
    mock_client.chat.completions.create.return_value = MagicMock(
        choices=[
            MagicMock(
                message=MagicMock(
                    content=(
                        '{"is_valid_news": true, "title": "GPT update", '
                        '"author": "OpenAI", "published_at": "2024-06-01T10:00:00Z", '
                        '"summary": "A factual summary.", "tags": ["llms"], '
                        '"missing_fields": [], "invalid_reason": null}'
                    )
                )
            )
        ]
    )

    result = extract_from_text("Article body about GPT.")

    assert result["is_valid_news"] is True
    assert result["title"] == "GPT update"
    assert result["author"] == "OpenAI"
    assert result["tags"] == ["llms"]
    assert result["published_at"].year == 2024


@patch("apps.extractor.service.OpenAI")
@patch("apps.extractor.service.get_effective_llm_settings")
@patch("apps.extractor.service._build_client")
def test_extract_from_text_falls_back_to_openai_on_failure(mock_build_client, mock_get_llm_settings, mock_openai_class, settings):
    from unittest.mock import ANY
    settings.OPENAI_FALLBACK_MODEL = "test-fallback-model"
    mock_get_llm_settings.return_value = ("http://local-llm-url/v1", "local-model")
    
    # Primary client (local LLM) raises exception
    mock_local_client = MagicMock()
    mock_local_client.chat.completions.create.side_effect = Exception("Local LLM down")
    mock_build_client.return_value = mock_local_client

    # Fallback client (cloud OpenAI) succeeds
    mock_fallback_client = MagicMock()
    mock_openai_class.return_value = mock_fallback_client
    mock_fallback_client.chat.completions.create.return_value = MagicMock(
        choices=[
            MagicMock(
                message=MagicMock(
                    content=(
                        '{"is_valid_news": true, "title": "Fallback GPT update", '
                        '"author": "OpenAI Cloud", "published_at": "2024-06-01T10:00:00Z", '
                        '"summary": "A fallback summary.", "tags": ["llms"], '
                        '"missing_fields": [], "invalid_reason": null}'
                    )
                )
            )
        ]
    )

    result = extract_from_text("Article body about GPT.")

    assert result["is_valid_news"] is True
    assert result["title"] == "Fallback GPT update"
    assert result["author"] == "OpenAI Cloud"
    assert result["tags"] == ["llms"]
    assert result["published_at"].year == 2024
    
    # Assert that fallback was initialized with no custom base_url
    mock_openai_class.assert_called_once_with(api_key=ANY)
    # Verify fallback call used test-fallback-model
    mock_fallback_client.chat.completions.create.assert_called_once()
    kwargs = mock_fallback_client.chat.completions.create.call_args[1]
    assert kwargs["model"] == "test-fallback-model"
