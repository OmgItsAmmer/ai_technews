from django.test import TestCase
from unittest.mock import patch
from apps.extraction import validators, service

class ValidatorsTest(TestCase):
    def test_clean_tags(self):
        # Valid tags
        self.assertEqual(validators.clean_tags(["llms", "research"]), ["llms", "research"])
        # Mix of valid and invalid
        self.assertEqual(validators.clean_tags(["llms", "invalid-tag", "robotics"]), ["llms", "robotics"])
        # Only invalid
        self.assertEqual(validators.clean_tags(["banana", "apple"]), [])
        # Non-list input
        self.assertEqual(validators.clean_tags("llms"), [])

    def test_parse_date(self):
        # Valid dates
        self.assertIsNotNone(validators.parse_date("2026-06-20T10:00:00Z"))
        self.assertIsNotNone(validators.parse_date("June 20, 2026"))
        # Invalid date
        self.assertIsNone(validators.parse_date("not-a-date"))
        # None date
        self.assertIsNone(validators.parse_date(None))

    def test_recompute_missing_fields(self):
        # All present
        metadata = {
            "title": "A Title",
            "author": "An Author",
            "published_at": "2026-06-20T10:00:00Z",
            "summary": "A short summary.",
            "tags": ["llms"],
            "missing_fields": []
        }
        self.assertEqual(validators.recompute_missing_fields(metadata), [])
        
        # Missing author and date
        metadata = {
            "title": "A Title",
            "author": "",
            "published_at": None,
            "summary": "A short summary.",
            "tags": ["llms"],
            "missing_fields": []
        }
        self.assertEqual(validators.recompute_missing_fields(metadata), ["author", "published_at"])
        
        # Missing everything
        metadata = {
            "title": None,
            "author": None,
            "published_at": None,
            "summary": None,
            "tags": [],
            "missing_fields": []
        }
        self.assertEqual(validators.recompute_missing_fields(metadata), ["author", "published_at", "summary", "tags", "title"])

class ExtractionServiceTest(TestCase):
    @patch("apps.extraction.client.call_openai_extractor")
    def test_extract_metadata_text_mode_success(self, mock_openai):
        mock_openai.return_value = {
            "is_valid_news": True,
            "title": "OpenAI released GPT-5",
            "author": "Jane Doe",
            "published_at": "2026-06-20T10:00:00Z",
            "summary": "OpenAI announced GPT-5 Turbo today.",
            "tags": ["llms", "banana"],  # 'banana' is invalid
            "missing_fields": []
        }
        
        result = service.extract_metadata("text", "Some article text")
        
        self.assertTrue(result["is_valid_news"])
        self.assertEqual(result["title"], "OpenAI released GPT-5")
        # 'banana' should have been cleaned out
        self.assertEqual(result["tags"], ["llms"])
        # 'tags' should have been added to missing_fields if tags array became empty,
        # but since 'llms' is left, missing_fields is empty.
        self.assertEqual(result["missing_fields"], [])

    @patch("apps.extraction.client.call_openai_extractor")
    def test_extract_metadata_invalid_news(self, mock_openai):
        mock_openai.return_value = {
            "is_valid_news": False,
            "title": None,
            "author": None,
            "published_at": None,
            "summary": "This is a recipe.",
            "tags": [],
            "missing_fields": []
        }
        
        result = service.extract_metadata("text", "Instructions to bake cookies")
        
        self.assertFalse(result["is_valid_news"])
        self.assertEqual(result["summary"], "This is a recipe.")
        # Missing fields should be auto-recomputed for invalid news as well
        self.assertTrue("title" in result["missing_fields"])


class LlmClientFallbackTest(TestCase):
    from django.test import override_settings

    @override_settings(OPENAI_FALLBACK_MODEL="test-fallback-model")
    @patch("apps.extraction.client.OpenAI")
    @patch("apps.extraction.client.get_effective_llm_settings")
    @patch("apps.extraction.client.get_effective_api_key")
    def test_call_openai_extractor_falls_back_on_failure(self, mock_api_key, mock_get_llm_settings, mock_openai_class):
        from unittest.mock import MagicMock
        from apps.extraction import client
        mock_get_llm_settings.return_value = ("http://local-llm-url/v1", "local-model")
        mock_api_key.return_value = "fake-key"
        
        # Primary client (local LLM) raises exception
        mock_local_client = MagicMock()
        mock_local_client.chat.completions.create.side_effect = Exception("Local LLM failed")
        
        # Fallback client (cloud OpenAI) succeeds
        mock_fallback_client = MagicMock()
        mock_fallback_client.chat.completions.create.return_value = MagicMock(
            choices=[
                MagicMock(
                    message=MagicMock(
                        content=(
                            '{"is_valid_news": true, "title": "Cloud Title", '
                            '"author": "Cloud Author", "published_at": "2026-06-20T10:00:00Z", '
                            '"summary": "Cloud summary.", "tags": ["llms"]}'
                        )
                    )
                )
            ]
        )
        
        # mock_openai_class gets called twice (first for local client, second for cloud client)
        mock_openai_class.side_effect = [mock_local_client, mock_fallback_client]
        
        result = client.call_openai_extractor("Some tech article content")
        
        self.assertTrue(result["is_valid_news"])
        self.assertEqual(result["title"], "Cloud Title")
        self.assertEqual(result["author"], "Cloud Author")
        
        # Assert calls to OpenAI client constructor
        self.assertEqual(mock_openai_class.call_count, 2)
        
        # First constructor call (local LLM)
        mock_openai_class.assert_any_call(base_url="http://local-llm-url/v1", api_key="fake-key")
        
        # Second constructor call (cloud LLM fallback)
        mock_openai_class.assert_any_call(api_key="fake-key")
        
        # Verify fallback call parameters
        mock_fallback_client.chat.completions.create.assert_called_once()
        kwargs = mock_fallback_client.chat.completions.create.call_args[1]
        self.assertEqual(kwargs["model"], "test-fallback-model")
