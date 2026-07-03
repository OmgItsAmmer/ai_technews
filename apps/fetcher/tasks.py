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


from apps.fetcher.models import PipelineLog


def _candidate_entries(source: Source) -> list[FeedEntry]:
    if source.rss_url:
        return fetch_rss(source.rss_url)

    links = discover_article_links(source.homepage_url)
    return [
        FeedEntry(link=link, title=link, published_at=None, summary="", author=None)
        for link in links
    ]


def _rss_first(value, fallback):
    """Use RSS value when present; otherwise fall back to LLM/scraped metadata."""
    if isinstance(value, str):
        return value.strip() or fallback
    if value is not None:
        return value
    return fallback


def _resolve_post_fields(
    entry: FeedEntry, metadata: dict, *, prefer_rss: bool
) -> dict:
    """Merge RSS feed fields with LLM extraction, preferring RSS when available."""
    if prefer_rss:
        return {
            "title": _rss_first(entry.title, metadata.get("title")),
            "published_at": _rss_first(entry.published_at, metadata.get("published_at")),
            "summary": _rss_first(entry.summary, metadata.get("summary")) or "",
            "author": _rss_first(entry.author, metadata.get("author")),
        }
    return {
        "title": metadata.get("title") or entry.title,
        "published_at": metadata.get("published_at") or entry.published_at,
        "summary": metadata.get("summary") or "",
        "author": metadata.get("author"),
    }


def _save_post(
    source: Source,
    entry: FeedEntry,
    body_text: str,
    metadata: dict,
    *,
    prefer_rss: bool = False,
) -> bool:
    if not metadata.get("is_valid_news"):
        logger.info(
            "Skipping invalid news for source=%s url=%s reason=%s",
            source.name,
            entry.link,
            metadata.get("invalid_reason"),
        )
        return False

    fields = _resolve_post_fields(entry, metadata, prefer_rss=prefer_rss)

    from django.db import IntegrityError
    try:
        Post.objects.create(
            source=source,
            title=fields["title"],
            original_url=entry.link,
            author=fields["author"],
            published_at=fields["published_at"],
            raw_content=body_text,
            summary=fields["summary"],
            tags=metadata.get("tags") or [],
            status=PostStatus.APPROVED,
            url_hash=compute_url_hash(entry.link),
        )
        return True
    except IntegrityError:
        logger.warning("Post with url %s already exists in db", entry.link)
        return False


def _process_source(source: Source, log: PipelineLog = None) -> int:
    saved_count = 0
    articles_details = []

    try:
        # Limit to latest 30 entries to prevent queue clogging
        entries = _candidate_entries(source)[:30]
        if log:
            log.articles_scraped = len(entries)
            log.save(update_fields=["articles_scraped"])
    except Exception as exc:
        logger.exception("Failed to fetch candidate entries for %s", source.name)
        if log:
            log.error_message = f"Failed to fetch candidate entries: {exc}"
            log.save(update_fields=["error_message"])
        raise

    for entry in entries:
        article_log = {
            "url": entry.link,
            "title": entry.title,
            "steps": {}
        }

        # Step 1: Deduplication
        if not is_new_url(entry.link):
            logger.debug("Duplicate URL skipped: %s", entry.link)
            if log:
                article_log["steps"]["deduplication"] = {"status": "skipped", "is_new": False}
                articles_details.append(article_log)
            continue

        if log:
            article_log["steps"]["deduplication"] = {"status": "success", "is_new": True}

        # Step 2: Scraping
        import time
        start_scrape = time.time()
        body_text = extract_article_text(entry.link)
        duration_scrape = int((time.time() - start_scrape) * 1000)

        if not body_text:
            logger.warning("No article text extracted for %s", entry.link)
            from apps.fetcher.dedup import remove_seen_url
            remove_seen_url(entry.link)
            if log:
                article_log["steps"]["scraping"] = {"status": "failed", "error": "No text extracted", "duration_ms": duration_scrape}
                articles_details.append(article_log)
            continue

        if log:
            article_log["steps"]["scraping"] = {"status": "success", "chars_extracted": len(body_text), "duration_ms": duration_scrape}

        # Step 3: LLM Extraction & Validation
        start_extract = time.time()
        try:
            metadata = extract_from_text(body_text)
            duration_extract = int((time.time() - start_extract) * 1000)

            is_valid = metadata.get("is_valid_news", False)
            if log:
                article_log["steps"]["metadata_extraction"] = {
                    "status": "success",
                    "is_valid_news": is_valid,
                    "extracted_title": metadata.get("title"),
                    "tags": metadata.get("tags") or [],
                    "duration_ms": duration_extract,
                    "invalid_reason": metadata.get("invalid_reason")
                }

            # Step 4: Storage
            if _save_post(
                source,
                entry,
                body_text,
                metadata,
                prefer_rss=bool(source.rss_url),
            ):
                saved_count += 1
                if log:
                    article_log["steps"]["storage"] = {"status": "saved"}
            else:
                if log:
                    if not is_valid:
                        article_log["steps"]["storage"] = {"status": "skipped", "reason": "invalid_news"}
                    else:
                        article_log["steps"]["storage"] = {"status": "duplicate"}
        except Exception as exc:
            duration_extract = int((time.time() - start_extract) * 1000)
            logger.error("Failed to extract metadata for %s: %s", entry.link, exc)
            from apps.fetcher.dedup import remove_seen_url
            remove_seen_url(entry.link)
            if log:
                article_log["steps"]["metadata_extraction"] = {"status": "failed", "error": str(exc), "duration_ms": duration_extract}
                articles_details.append(article_log)
            continue

        if log:
            articles_details.append(article_log)

    source.last_fetched_at = timezone.now()
    source.save(update_fields=["last_fetched_at", "updated_at"])

    if log:
        log.articles_saved = saved_count
        log.details = {"articles": articles_details}
        log.save(update_fields=["articles_saved", "details"])

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

    log = PipelineLog.objects.create(source=source, status="running")

    try:
        res = _process_source(source, log)
        log.status = "success"
        log.finished_at = timezone.now()
        log.save(update_fields=["status", "finished_at"])
        return res
    except Exception as exc:
        import traceback
        log.status = "failed"
        log.error_message = f"{exc}\n{traceback.format_exc()}"
        log.finished_at = timezone.now()
        log.save(update_fields=["status", "error_message", "finished_at"])
        logger.exception("Fetch failed for source %s (%s)", source.name, source_id)

        # Avoid retrying the task for persistent 4xx Client Errors (e.g. 403 Forbidden, 404 Not Found)
        from httpx import HTTPStatusError
        if isinstance(exc, HTTPStatusError) and exc.response is not None and 400 <= exc.response.status_code < 500:
            logger.warning("Not retrying fetch_source task due to persistent 4xx Client Error: %s", exc)
            return 0

        raise self.retry(exc=exc)


@shared_task
def sync_scrutinize_task(days: int = 30, limit: int = 50) -> dict:
    """Run bidirectional sync with Scrutinize vector DB."""
    from apps.posts.services.sync_scrutinize import sync_scrutinize_posts

    logger.info("Executing sync_scrutinize_task...")
    try:
        result = sync_scrutinize_posts(days=days, limit=limit)
        return {
            "status": "success",
            "deleted_count": result.deleted_count,
            "uploaded_count": result.uploaded_count,
            "job_ids": result.job_ids,
        }
    except Exception as exc:
        logger.exception("Failed to sync with Scrutinize: %s", exc)
        return {"status": "failed", "error": str(exc)}


@shared_task
def finalize_fetch_pipeline(fetch_results: list[int], run_id: str) -> dict:
    """After all source fetches complete, sync to Scrutinize and queue embedding tracking."""
    from apps.frontend.fetch_run import get_fetch_run, update_fetch_run
    from apps.posts.services.sync_scrutinize import sync_scrutinize_posts

    articles_saved = sum(r or 0 for r in (fetch_results or []))
    state = get_fetch_run(run_id) or {}
    update_fetch_run(
        run_id,
        sources_done=state.get("sources_total", 0),
        articles_saved=articles_saved,
        phase="syncing",
        message="Uploading articles to Scrutinize (30-day window)…",
    )

    try:
        result = sync_scrutinize_posts(days=30, limit=500)
    except Exception as exc:
        logger.exception("Scrutinize sync failed during fetch pipeline: %s", exc)
        update_fetch_run(
            run_id,
            phase="failed",
            error=str(exc),
            message="Failed to sync articles with Scrutinize.",
        )
        return {"status": "failed", "error": str(exc)}

    if result.job_ids:
        update_fetch_run(
            run_id,
            phase="embedding",
            deleted_count=result.deleted_count,
            uploaded_count=result.uploaded_count,
            job_ids=result.job_ids,
            embedding_total=len(result.job_ids),
            embedding_done=0,
            embedding_failed=0,
            message=f"Embedding {len(result.job_ids)} article(s) for AI search…",
        )
    else:
        update_fetch_run(
            run_id,
            phase="done",
            deleted_count=result.deleted_count,
            uploaded_count=result.uploaded_count,
            message="Fetch complete. AI index is up to date.",
        )

    return {
        "status": "success",
        "articles_saved": articles_saved,
        "uploaded_count": result.uploaded_count,
        "job_ids": result.job_ids,
    }


@shared_task
def fetch_all_sources(run_id: str | None = None) -> dict[str, int | str]:
    """Dispatch a fetch task for every active source, optionally tracked by ``run_id``."""
    from celery import chord, group

    from apps.frontend.fetch_run import update_fetch_run

    source_ids = list(
        Source.objects.filter(is_active=True).values_list("id", flat=True)
    )

    if run_id:
        update_fetch_run(run_id, sources_total=len(source_ids))
        if source_ids:
            chord(
                group(fetch_source.s(source_id) for source_id in source_ids),
                finalize_fetch_pipeline.s(run_id),
            ).apply_async()
        else:
            finalize_fetch_pipeline.delay([], run_id)
    else:
        for source_id in source_ids:
            fetch_source.delay(source_id)
        sync_scrutinize_task.apply_async(countdown=60)

    logger.info("Dispatched fetch_source for %s active sources", len(source_ids))
    payload: dict[str, int | str] = {"dispatched": len(source_ids)}
    if run_id:
        payload["run_id"] = run_id
    return payload
