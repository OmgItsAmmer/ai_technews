import json
import logging
from openai import OpenAI
from django.conf import settings
from apps.extraction.prompts import SYSTEM_PROMPT, USER_PROMPT_TEMPLATE

logger = logging.getLogger(__name__)

def call_openai_extractor(content: str) -> dict:
    """
    Calls OpenAI to extract metadata from the provided content.
    If the API key is not configured or is a placeholder, and no base_url is set,
    falls back to a smart mock.
    """
    api_key = getattr(settings, 'OPENAI_API_KEY', '')
    base_url = getattr(settings, 'OPENAI_BASE_URL', None)
    model = getattr(settings, 'OPENAI_MODEL', 'gpt-4o-mini')
    
    # If no real OpenAI API key is configured AND no custom base_url is set, fall back to mock
    is_placeholder_key = not api_key or api_key == 'sk-...' or api_key.startswith('sk-mock')
    if is_placeholder_key and not base_url:
        logger.info("Using mock response because no real OpenAI API Key and no custom base_url was found.")
        return get_mock_response(content)
        
    try:
        if base_url:
            client = OpenAI(
                base_url=base_url,
                api_key=api_key or "not-needed"
            )
        else:
            client = OpenAI(api_key=api_key)

        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": USER_PROMPT_TEMPLATE.format(content=content)}
            ],
            temperature=0.0,
            response_format={"type": "json_object"}  # Request JSON mode
        )
        raw_response = response.choices[0].message.content.strip()
        return parse_json_response(raw_response)
    except Exception as e:
        logger.error(f"OpenAI API call failed: {e}")
        # Return fallback dictionary conforming to the contract
        return {
            "is_valid_news": False,
            "title": None,
            "author": None,
            "published_at": None,
            "summary": f"Failed to connect to AI extraction service: {str(e)}",
            "tags": [],
            "missing_fields": ["title", "author", "published_at", "summary", "tags"]
        }

def parse_json_response(raw_response: str) -> dict:
    """
    Parses raw response string into dict. Strips markdown code block fences and retries once if needed.
    """
    try:
        return json.loads(raw_response)
    except json.JSONDecodeError:
        # Strip ```json and ``` fences and try once more
        cleaned = raw_response.strip()
        if cleaned.startswith("```json"):
            cleaned = cleaned[7:]
        elif cleaned.startswith("```"):
            cleaned = cleaned[3:]
        if cleaned.endswith("```"):
            cleaned = cleaned[:-3]
        cleaned = cleaned.strip()
        
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError as e:
            logger.error(f"JSON parsing failed after cleanup: {e}. Raw response: {raw_response}")
            raise e

def get_mock_response(content: str) -> dict:
    """
    Returns a mocked response for testing without OpenAI API keys.
    """
    lower_content = content.lower()
    
    # 1. If the content is clearly a non-tech topic (recipe, weather, personal blog)
    if "recipe" in lower_content or "ingredients" in lower_content or "weather" in lower_content:
        return {
            "is_valid_news": False,
            "title": None,
            "author": None,
            "published_at": None,
            "summary": "This content is not related to technology or artificial intelligence (it appears to be a recipe, weather, or non-tech topic).",
            "tags": [],
            "missing_fields": ["title", "author", "published_at", "summary", "tags"]
        }
        
    # 2. Check if it's text-mode pasting with missing date/author
    is_missing_author = "author" not in lower_content and "by " not in lower_content
    is_missing_date = "202" not in lower_content and "published" not in lower_content
    
    title = "OpenAI releases GPT-5 Turbo with longer context windows"
    author = None if is_missing_author else "Jane Doe"
    published_at = None if is_missing_date else "2026-06-20T10:00:00Z"
    
    if "nvidia" in lower_content:
        title = "NVIDIA Announces Next-Generation Blackwell Ultra GPU Architecture"
    elif "apple" in lower_content:
        title = "Apple Intelligence to Roll Out Globally with Advanced Siri Capabilities"
        
    # Setup tags
    tags = ["llms", "developer-tools"]
    if "cyber" in lower_content or "security" in lower_content:
        tags = ["cybersecurity"]
    elif "robot" in lower_content:
        tags = ["robotics"]
        
    return {
        "is_valid_news": True,
        "title": title,
        "author": author,
        "published_at": published_at,
        "summary": "OpenAI announced GPT-5 Turbo, expanding context length and lowering latency. The release targets enterprise developers building long-document agents. Pricing remains unchanged from the prior Turbo tier.",
        "tags": tags,
        "missing_fields": []
    }
