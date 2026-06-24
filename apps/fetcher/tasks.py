import logging

from celery import shared_task
from django.utils import timezone

from apps.extractor.service import extract_from_text
from apps.fetcher.dedup import is_new_url
from apps.fetcher.rss import FeedEntry, fetch_rss
from apps.fetcher.scraper import discover_article_links, extract_article_text
from apps.posts.models import Post, PostStatus, compute_url_hash
from apps.sources.models import Source

logger = logging.getLogger(__name__)


def _candidate_entries(source: Source) -> list[FeedEntry]:
    if source.rss_url:
        return fetch_rss(source.rss_url)

    links = discover_article_links(source.homepage_url)
    return [
        FeedEntry(link=link, title=link, published_at=None, summary="")
        for link in links
    ]


def _save_post(source: Source, entry: FeedEntry, body_text: str, metadata: dict) -> bool:
    if not metadata.get("is_valid_news"):
        logger.info(
            "Skipping invalid news for source=%s url=%s reason=%s",
            source.name,
            entry.link,
            metadata.get("invalid_reason"),
        )
        return False

    title = metadata.get("title") or entry.title
    published_at = metadata.get("published_at") or entry.published_at

    Post.objects.create(
        source=source,
        title=title,
        original_url=entry.link,
        author=metadata.get("author"),
        published_at=published_at,
        raw_content=body_text,
        summary=metadata.get("summary") or "",
        tags=metadata.get("tags") or [],
        status=PostStatus.PENDING,
        url_hash=compute_url_hash(entry.link),
    )
    return True


def _process_source(source: Source) -> int:
    saved_count = 0

    for entry in _candidate_entries(source):
        if not is_new_url(entry.link):
            logger.debug("Duplicate URL skipped: %s", entry.link)
            continue

        body_text = extract_article_text(entry.link)
        if not body_text:
            logger.warning("No article text extracted for %s", entry.link)
            continue

        metadata = extract_from_text(body_text)
        if _save_post(source, entry, body_text, metadata):
            saved_count += 1

    source.last_fetched_at = timezone.now()
    source.save(update_fields=["last_fetched_at", "updated_at"])
    logger.info("Source %s: saved %s new posts", source.name, saved_count)
    return saved_count


@shared_task(bind=True, max_retries=3, default_retry_delay=300)
def fetch_source(self, source_id: int) -> int:
    """Fetch articles for a single source and save pending posts."""
    try:
        source = Source.objects.get(pk=source_id, is_active=True)
    except Source.DoesNotExist:
        logger.warning("Source %s not found or inactive", source_id)
        return 0

    try:
        return _process_source(source)
    except Exception as exc:
        logger.exception("Fetch failed for source %s (%s)", source.name, source_id)
        raise self.retry(exc=exc)


@shared_task
def fetch_all_sources() -> dict[str, int]:
    """Dispatch a fetch task for every active source."""
    source_ids = list(
        Source.objects.filter(is_active=True).values_list("id", flat=True)
    )
    for source_id in source_ids:
        fetch_source.delay(source_id)

    logger.info("Dispatched fetch_source for %s active sources", len(source_ids))
    return {"dispatched": len(source_ids)}
