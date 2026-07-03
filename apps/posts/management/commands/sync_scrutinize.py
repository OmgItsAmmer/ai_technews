import logging

from django.core.management.base import BaseCommand

from apps.posts.services.sync_scrutinize import sync_scrutinize_posts

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Sync articles with Scrutinize vector storage (upload recent 30 days, delete older than 30 days)."

    def add_arguments(self, parser):
        parser.add_argument("--days", type=int, default=30, help="Number of days for retention window.")
        parser.add_argument("--limit", type=int, default=100, help="Max posts to upload in a single run.")

    def handle(self, *args, **options):
        days = options["days"]
        limit = options["limit"]

        self.stdout.write(f"Starting Scrutinize sync (retention: {days} days)...")
        result = sync_scrutinize_posts(days=days, limit=limit)

        summary = (
            f"Sync completed:\n"
            f" - Deleted expired database records: {result.deleted_count}\n"
            f" - Pruned remote orphaned files: {result.orphaned_deleted}\n"
            f" - Uploaded recent articles: {result.uploaded_count}\n"
            f" - Embedding jobs queued: {len(result.job_ids)}"
        )
        self.stdout.write(self.style.SUCCESS(summary))
