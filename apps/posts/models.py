import hashlib

from django.contrib.postgres.indexes import GinIndex
from django.db import models

from apps.sources.models import Source


class PostStatus(models.TextChoices):
    PENDING = "pending", "Pending"
    APPROVED = "approved", "Approved"
    REJECTED = "rejected", "Rejected"


def compute_url_hash(url: str) -> str:
    return hashlib.sha256(url.encode("utf-8")).hexdigest()


class Post(models.Model):
    source = models.ForeignKey(
        Source,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="posts",
    )
    title = models.CharField(max_length=500)
    original_url = models.URLField(max_length=1000, blank=True, null=True, unique=True)
    author = models.CharField(max_length=200, blank=True, null=True)
    published_at = models.DateTimeField(blank=True, null=True)
    fetched_at = models.DateTimeField(auto_now_add=True)
    raw_content = models.TextField(blank=True, default="")
    summary = models.TextField(blank=True, default="")
    tags = models.JSONField(default=list, blank=True)
    status = models.CharField(
        max_length=20,
        choices=PostStatus.choices,
        default=PostStatus.PENDING,
    )
    url_hash = models.CharField(max_length=64, blank=True, db_index=True)

    class Meta:
        ordering = ["-published_at", "-fetched_at"]
        indexes = [
            models.Index(fields=["status", "published_at"]),
            GinIndex(fields=["tags"], name="posts_tags_gin"),
        ]

    def __str__(self):
        return self.title

    def save(self, *args, **kwargs):
        if self.original_url and not self.url_hash:
            self.url_hash = compute_url_hash(self.original_url)
        super().save(*args, **kwargs)


class KeywordSetting(models.Model):
    keywords = models.TextField(
        help_text="Enter up to 10 comma-separated keywords.",
        blank=True,
        default=""
    )

    class Meta:
        verbose_name = "Keyword Settings"
        verbose_name_plural = "Keyword Settings"

    def __str__(self):
        return "Keyword Settings"

