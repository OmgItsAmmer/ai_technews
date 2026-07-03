"""Bidirectional sync between Antix News posts and Scrutinize vector storage."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import timedelta

from django.utils import timezone

from apps.frontend.scrutinize import ScrutinizeClient
from apps.posts.models import Post

logger = logging.getLogger(__name__)


@dataclass
class SyncScrutinizeResult:
    deleted_count: int = 0
    orphaned_deleted: int = 0
    uploaded_count: int = 0
    job_ids: list[str] = field(default_factory=list)
    file_ids: list[str] = field(default_factory=list)


def sync_scrutinize_posts(
    *,
    days: int = 30,
    limit: int = 100,
    upload_delay_seconds: float = 1.0,
) -> SyncScrutinizeResult:
    """Upload recent posts to Scrutinize and prune embeddings older than ``days``."""
    cutoff_date = timezone.now() - timedelta(days=days)
    client = ScrutinizeClient()
    result = SyncScrutinizeResult()

    old_posts = Post.objects.filter(published_at__lt=cutoff_date, scrutinize_file_id__isnull=False)
    for post in old_posts:
        logger.info("Deleting expired article %s from Scrutinize", post.id)
        if client.delete_file(post.scrutinize_file_id):
            post.scrutinize_file_id = None
            post.save(update_fields=["scrutinize_file_id"])
            result.deleted_count += 1

    remote_files = client.list_library()
    for remote in remote_files:
        file_id = remote.get("id") or remote.get("file_id")
        fname = remote.get("filename", "")
        if not fname.startswith("post_") or not fname.endswith(".txt"):
            continue
        try:
            post_id = int(fname[5:-4])
        except ValueError:
            continue
        post = Post.objects.filter(id=post_id).first()
        if post and post.published_at and post.published_at >= cutoff_date:
            continue
        logger.info("Pruning orphaned/old remote file %s", fname)
        if file_id and client.delete_file(str(file_id)):
            result.orphaned_deleted += 1
            if post and post.scrutinize_file_id:
                post.scrutinize_file_id = None
                post.save(update_fields=["scrutinize_file_id"])

    uploaded = 0
    while uploaded < limit:
        batch_size = min(limit - uploaded, 50)
        recent_posts = list(
            Post.objects.filter(
                status="approved",
                published_at__gte=cutoff_date,
                scrutinize_file_id__isnull=True,
            ).order_by("-published_at")[:batch_size]
        )
        if not recent_posts:
            break

        for post in recent_posts:
            logger.info("Uploading article %s to Scrutinize", post.id)
            upload = client.upload_post(post)
            if upload and upload.get("file_id"):
                post.scrutinize_file_id = upload["file_id"]
                post.save(update_fields=["scrutinize_file_id"])
                result.uploaded_count += 1
                uploaded += 1
                result.file_ids.append(str(upload["file_id"]))
                if upload.get("job_id"):
                    result.job_ids.append(str(upload["job_id"]))
            if upload_delay_seconds:
                time.sleep(upload_delay_seconds)

        if len(recent_posts) < batch_size:
            break

    return result
