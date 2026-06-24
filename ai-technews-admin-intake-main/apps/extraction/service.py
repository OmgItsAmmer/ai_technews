import logging
from apps.extraction import scraper, client, validators

logger = logging.getLogger(__name__)

def extract_metadata(mode: str, content: str) -> dict:
    """
    Coordinates the extraction pipeline:
    1. Fetches/extracts content if mode is 'url'.
    2. Caps content at 8000 characters.
    3. Calls OpenAI extractor.
    4. Cleans tags.
    5. Parses publication date.
    6. Recomputes missing fields.
    """
    content = (content or "").strip()
    if not content:
        return {
            "is_valid_news": False,
            "title": None,
            "author": None,
            "published_at": None,
            "summary": "Content is required.",
            "tags": [],
            "missing_fields": ["title", "author", "published_at", "summary", "tags"]
        }

    # 1. Scraping if mode is URL
    if mode == "url":
        extracted_text = scraper.fetch_and_extract(content)
        if not extracted_text:
            return {
                "is_valid_news": False,
                "title": None,
                "author": None,
                "published_at": None,
                "summary": "Could not extract readable text from the provided URL.",
                "tags": [],
                "missing_fields": ["title", "author", "published_at", "summary", "tags"]
            }
        text_to_analyze = extracted_text
    else:
        text_to_analyze = content

    # 2. Cap text at 8000 characters
    text_to_analyze = text_to_analyze[:8000]

    # 3. Call OpenAI extractor (or mock)
    metadata = client.call_openai_extractor(text_to_analyze)

    # If the news is marked as invalid, return it early (will contain is_valid_news = False and summary = reason)
    if not metadata.get("is_valid_news", False):
        metadata["is_valid_news"] = False
        metadata["title"] = None
        metadata["author"] = None
        metadata["published_at"] = None
        metadata["tags"] = []
        metadata["missing_fields"] = validators.recompute_missing_fields(metadata)
        return metadata

    # 4. Run validators.clean_tags()
    cleaned_tags = validators.clean_tags(metadata.get("tags", []))
    metadata["tags"] = cleaned_tags

    # 5. Run validators.parse_date()
    raw_date = metadata.get("published_at")
    parsed_date = validators.parse_date(raw_date)
    metadata["published_at"] = parsed_date

    # 6. Recompute missing_fields
    metadata["missing_fields"] = validators.recompute_missing_fields(metadata)
    
    # Store raw text used for extraction
    metadata["raw_input"] = text_to_analyze

    return metadata
