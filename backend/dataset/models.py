from django.db import models

from core.models import TimeStampedModel


class RawNewsItem(TimeStampedModel):
    source_name = models.CharField(max_length=255)
    source_url = models.URLField(max_length=1000, blank=True, default="")
    url = models.URLField(max_length=1000, unique=True)
    title = models.TextField(blank=True, default="")
    summary = models.TextField(blank=True, default="")
    content = models.TextField(blank=True, default="")
    cleaned_text = models.TextField(blank=True, default="")
    published_at = models.DateTimeField(null=True, blank=True)
    fetched_at = models.DateTimeField(null=True, blank=True)
    raw_payload = models.JSONField(blank=True, default=dict)

    class Meta:
        ordering = ["-published_at"]
        indexes = [
            models.Index(fields=["published_at"]),
            models.Index(fields=["source_name"]),
        ]

    def __str__(self) -> str:
        label = self.title or self.url
        return f"{self.source_name}: {label}"
