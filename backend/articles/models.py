from django.db import models

from core.models import PublishableModel, TimeStampedModel


class Article(PublishableModel):
    url = models.URLField(max_length=1000, unique=True)
    source = models.CharField(max_length=255)
    published_at = models.DateTimeField()
    fetched_at = models.DateTimeField()
    title = models.TextField(blank=True, default="")
    body = models.TextField(blank=True, default="")
    language = models.CharField(max_length=16, blank=True, default="")

    class Meta:
        ordering = ["-published_at"]
        indexes = [
            models.Index(fields=["published_at"]),
            models.Index(fields=["source"]),
        ]

    def __str__(self) -> str:
        return f"{self.source}:{self.published_at:%Y-%m-%d}"


class HourlyBrief(TimeStampedModel):
    hour_start = models.DateTimeField(unique=True)
    hour_end = models.DateTimeField()
    slug = models.SlugField(max_length=64, unique=True)
    title = models.TextField(blank=True, default="")
    summary = models.TextField(blank=True, default="")
    references = models.JSONField(blank=True, default=list)
    article_count = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["-hour_start"]
        indexes = [
            models.Index(fields=["hour_start"]),
            models.Index(fields=["slug"]),
        ]

    def __str__(self) -> str:
        return f"Brief {self.hour_start:%Y-%m-%d %H:00}"
