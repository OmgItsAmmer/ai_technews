from dateutil import parser
from apps.posts.constants import TAG_CHOICES
import logging

logger = logging.getLogger(__name__)

# Single source of truth for allowed tag slugs
ALLOWED_TAG_SLUGS = {choice[0] for choice in TAG_CHOICES}

def clean_tags(tags: list) -> list:
    """
    Filters the tags list, keeping only those present in the ALLOWED_TAG_SLUGS.
    """
    if not isinstance(tags, list):
        return []
    return [str(tag).strip() for tag in tags if str(tag).strip() in ALLOWED_TAG_SLUGS]

def parse_date(date_str: str) -> str | None:
    """
    Parses a date string using python-dateutil and returns an ISO 8601 string.
    Returns None on failure.
    """
    if not date_str:
        return None
    try:
        dt = parser.parse(str(date_str))
        return dt.isoformat()
    except Exception as e:
        logger.warning(f"Date parsing failed for '{date_str}': {e}")
        return None

def recompute_missing_fields(metadata: dict) -> list[str]:
    """
    Recomputes the missing_fields list by checking all required fields:
    title, author, published_at, summary, tags.
    Appends any that are missing or empty to the existing missing_fields list,
    ensuring uniqueness.
    """
    missing = set(metadata.get("missing_fields", []))
    
    if not metadata.get("title") or not str(metadata["title"]).strip():
        missing.add("title")
    if not metadata.get("author") or not str(metadata["author"]).strip():
        missing.add("author")
    if not metadata.get("published_at"):
        missing.add("published_at")
    if not metadata.get("summary") or not str(metadata["summary"]).strip():
        missing.add("summary")
    if not metadata.get("tags") or len(metadata["tags"]) == 0:
        missing.add("tags")
        
    return sorted(list(missing))
