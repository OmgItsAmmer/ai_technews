import hashlib
from django.db import models
from django.contrib.postgres.indexes import GinIndex

class Post(models.Model):
    STATUS_CHOICES = [
        ("pending", "Pending"),
        ("approved", "Approved"),
        ("rejected", "Rejected"),
    ]
    title = models.CharField(max_length=120)
    original_url = models.URLField(max_length=500, unique=True, null=True, blank=True)
    url_hash = models.CharField(max_length=64, null=True, blank=True, db_index=True)
    author = models.CharField(max_length=255, null=True, blank=True)
    published_at = models.DateTimeField(null=True, blank=True)
    raw_input = models.TextField()  # pasted text/XML/JSON, or scraped article text
    summary = models.TextField()
    tags = models.JSONField(default=list)  # array of slugs, e.g. ["llms", "research"]
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default="pending")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=["status", "published_at"], name="post_status_pubdate_idx"),
            models.Index(fields=["url_hash"], name="post_urlhash_idx"),
            GinIndex(fields=["tags"], name="post_tags_gin_idx"),
        ]

    def save(self, *args, **kwargs):
        if self.original_url and not self.url_hash:
            self.url_hash = hashlib.sha256(self.original_url.encode()).hexdigest()
        super().save(*args, **kwargs)

    def __str__(self):
        return self.title
