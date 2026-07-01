import logging
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.frontend.scrutinize import ScrutinizeClient
from apps.posts.models import Post

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Sync articles with Scrutinize vector storage (upload recent 30 days, delete older than 30 days)."

    def add_arguments(self, parser):
        parser.add_argument("--days", type=int, default=30, help="Number of days for retention window.")
        parser.add_argument("--limit", type=int, default=100, help="Max posts to upload in a single run.")

    def handle(self, *args, **options):
        days = options["days"]
        limit = options["limit"]
        cutoff_date = timezone.now() - timedelta(days=days)
        client = ScrutinizeClient()

        self.stdout.write(f"Starting Scrutinize sync (cutoff date: {cutoff_date.isoformat()})...")

        # 1. RETENTION CLEANUP: Delete posts older than `days` that have scrutinize_file_id
        old_posts = Post.objects.filter(published_at__lt=cutoff_date, scrutinize_file_id__isnull=False)
        deleted_count = 0
        for p in old_posts:
            self.stdout.write(f"Deleting expired article ID {p.id} (published {p.published_at}) from Scrutinize...")
            if client.delete_file(p.scrutinize_file_id):
                p.scrutinize_file_id = None
                p.save(update_fields=["scrutinize_file_id"])
                deleted_count += 1

        # Also check remote library for any orphaned post files older than cutoff
        remote_files = client.list_library()
        orphaned_deleted = 0
        for f in remote_files:
            file_id = f.get("id") or f.get("file_id")
            fname = f.get("filename", "")
            if fname.startswith("post_") and fname.endswith(".txt"):
                try:
                    post_id = int(fname[5:-4])
                    post = Post.objects.filter(id=post_id).first()
                    if not post or (post.published_at and post.published_at < cutoff_date):
                        self.stdout.write(f"Pruning orphaned/old remote file {fname} (ID: {file_id})...")
                        if file_id and client.delete_file(file_id):
                            orphaned_deleted += 1
                            if post and post.scrutinize_file_id:
                                post.scrutinize_file_id = None
                                post.save(update_fields=["scrutinize_file_id"])
                except ValueError:
                    pass

        # 2. INGESTION: Upload recent approved posts lacking scrutinize_file_id
        recent_posts = Post.objects.filter(
            status="approved",
            published_at__gte=cutoff_date,
            scrutinize_file_id__isnull=True,
        ).order_by("-published_at")[:limit]

        uploaded_count = 0
        import time
        for p in recent_posts:
            self.stdout.write(f"Uploading recent article ID {p.id}: '{p.title[:50]}...' to Scrutinize...")
            res = client.upload_post(p)
            if res and res.get("file_id"):
                p.scrutinize_file_id = res["file_id"]
                p.save(update_fields=["scrutinize_file_id"])
                uploaded_count += 1
            time.sleep(1)

        summary = (
            f"Sync completed:\n"
            f" - Deleted expired database records: {deleted_count}\n"
            f" - Pruned remote orphaned files: {orphaned_deleted}\n"
            f" - Uploaded recent articles: {uploaded_count}"
        )
        self.stdout.write(self.style.SUCCESS(summary))
