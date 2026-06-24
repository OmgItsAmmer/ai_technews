from django.db import models


class SourceType(models.TextChoices):
    OFFICIAL = "official", "Official"
    MEDIA = "media", "Media"
    BLOG = "blog", "Blog"
    COMMUNITY = "community", "Community"
    RESEARCH = "research", "Research"


class Source(models.Model):
    name = models.CharField(max_length=200)
    homepage_url = models.URLField(max_length=500)
    rss_url = models.URLField(max_length=500, blank=True, null=True)
    source_type = models.CharField(max_length=20, choices=SourceType.choices)
    badge_label = models.CharField(max_length=50)
    is_active = models.BooleanField(default=True)
    fetch_interval_minutes = models.PositiveIntegerField(default=240)
    last_fetched_at = models.DateTimeField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name
