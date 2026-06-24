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


@patch("apps.extractor.service._build_client")
def test_extract_from_text_returns_structured_metadata(mock_build_client):
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
