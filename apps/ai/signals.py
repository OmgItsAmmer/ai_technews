"""Keep the AI index in step with posts: index on approve/edit, remove on delete/reject."""

import logging

from django.conf import settings
from django.db import transaction
from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from apps.posts.models import Post

logger = logging.getLogger(__name__)


def _enabled() -> bool:
    return settings.AI_BACKEND in ("antix", "shadow") and bool(settings.AI_SERVICE_KEY)


def _enqueue(post_id: int) -> None:
    from apps.ai.tasks import enqueue_ingest

    try:
        enqueue_ingest.delay(post_id)
    except Exception:  # broker down must never break saving a post
        logger.exception("could not enqueue AI ingest for post %s", post_id)


@receiver(post_save, sender=Post)
def on_post_saved(sender, instance: Post, **kwargs):
    if _enabled():
        post_id = instance.pk
        transaction.on_commit(lambda: _enqueue(post_id))


@receiver(post_delete, sender=Post)
def on_post_deleted(sender, instance: Post, **kwargs):
    if _enabled():
        post_id = instance.pk  # Django clears pk after delete; capture it now
        transaction.on_commit(lambda: _enqueue(post_id))
