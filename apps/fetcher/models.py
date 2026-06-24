from django.db import models
from apps.sources.models import Source


class PipelineLog(models.Model):
    source = models.ForeignKey(
        Source, on_delete=models.CASCADE, related_name="pipeline_logs"
    )
    started_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    status = models.CharField(max_length=50, default="running")
    articles_scraped = models.IntegerField(default=0)
    articles_saved = models.IntegerField(default=0)
    error_message = models.TextField(blank=True, null=True)
    details = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["-started_at"]

    def __str__(self):
        started_str = self.started_at.strftime("%Y-%m-%d %H:%M:%S") if self.started_at else "Pending"
        return f"{self.source.name} - {started_str} ({self.status})"
