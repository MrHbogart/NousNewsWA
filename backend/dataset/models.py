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


class RawCandle(TimeStampedModel):
    """Store raw 1-minute candle data for configured assets.

    Assets and series configuration live outside the `dataset` app; this
    model is intended to hold the gathered raw candles (1m) for ingestion
    and later processing by other apps.
    """
    asset_symbol = models.CharField(max_length=64)
    timestamp = models.DateTimeField()
    open = models.FloatField()
    high = models.FloatField()
    low = models.FloatField()
    close = models.FloatField()
    volume = models.FloatField(default=0)
    raw_payload = models.JSONField(blank=True, default=dict)

    class Meta:
        ordering = ["timestamp"]
        indexes = [models.Index(fields=["asset_symbol", "timestamp"])]

    def __str__(self) -> str:
        return f"{self.asset_symbol} @ {self.timestamp.isoformat()}"
