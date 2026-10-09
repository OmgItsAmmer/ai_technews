import logging

from celery import shared_task

from apps.ai.client import AIClient, AIUnavailable

logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=5, default_retry_delay=30)
def enqueue_ingest(self, post_id: int, force: bool = False) -> dict:
    """Tell the AI service to (re)index or remove a post. Idempotent on the service side."""
    try:
        return AIClient().ingest(post_id, force=force)
    except AIUnavailable as exc:
        logger.warning("AI service unavailable for post %s: %s", post_id, exc)
        raise self.retry(exc=exc, countdown=min(300, 30 * 2**self.request.retries)) from exc
