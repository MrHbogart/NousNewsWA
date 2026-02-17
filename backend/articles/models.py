import uuid

from django.db import models

from core.models import TimeStampedModel
from articles.slugging import build_article_slug


class Card(TimeStampedModel):
    TIMEFRAME_HOUR = "hour"
    TIMEFRAME_DAY = "day"
    TIMEFRAME_WEEK = "week"
    TIMEFRAME_MONTH = "month"

    TIMEFRAME_CHOICES = [
        (TIMEFRAME_HOUR, "Hour"),
        (TIMEFRAME_DAY, "Day"),
        (TIMEFRAME_WEEK, "Week"),
        (TIMEFRAME_MONTH, "Month"),
    ]

    STATUS_OPEN = "open"
    STATUS_FINAL = "final"

    STATUS_CHOICES = [
        (STATUS_OPEN, "Open"),
        (STATUS_FINAL, "Final"),
    ]

    uuid = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    timeframe = models.CharField(max_length=16, choices=TIMEFRAME_CHOICES)
    period_start = models.DateTimeField()
    period_end = models.DateTimeField()
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default=STATUS_OPEN)
    slug = models.SlugField(max_length=96, unique=True)
    title = models.TextField(blank=True, default="")
    summary = models.TextField(blank=True, default="")
    body = models.TextField(blank=True, default="")
    source_name = models.CharField(max_length=255, blank=True, default="")
    references = models.JSONField(blank=True, default=list)
    published_at = models.DateTimeField(null=True, blank=True)
    article_count = models.PositiveIntegerField(default=0)
    importance_score = models.PositiveSmallIntegerField(default=1)
    importance_reason = models.CharField(max_length=280, blank=True, default="")

    class Meta:
        ordering = ["-period_start"]
        constraints = [
            models.UniqueConstraint(
                fields=["timeframe", "period_start"],
                name="unique_card_per_timeframe",
            )
        ]

    def __str__(self) -> str:
        return f"{self.timeframe} {self.period_start:%Y-%m-%d %H:%M}"


class CardArticle(TimeStampedModel):
    KIND_MAIN = "main"
    KIND_SIDE = "side"

    KIND_CHOICES = [
        (KIND_MAIN, "Main"),
        (KIND_SIDE, "Side"),
    ]

    uuid = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    slug = models.SlugField(max_length=180, unique=True, blank=True, default="")
    card = models.ForeignKey(Card, on_delete=models.CASCADE, related_name="articles")
    kind = models.CharField(max_length=16, choices=KIND_CHOICES, default=KIND_MAIN)
    title = models.TextField(blank=True, default="")
    summary = models.TextField(blank=True, default="")
    body = models.TextField(blank=True, default="")
    references = models.JSONField(blank=True, default=list)
    impacts = models.JSONField(blank=True, default=list)
    time_window = models.CharField(max_length=16, blank=True, default="")
    published_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.card} {self.kind}"

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = build_article_slug(
                title=self.title,
                period_start=self.card.period_start,
                article_uuid=self.uuid,
                kind=self.kind,
            )
        super().save(*args, **kwargs)


class CardAsset(TimeStampedModel):
    card = models.ForeignKey(Card, on_delete=models.CASCADE, related_name="assets")
    series = models.ForeignKey("articles.AssetSeries", on_delete=models.CASCADE, related_name="card_assets")
    label = models.CharField(max_length=64, blank=True, default="")

    class Meta:
        ordering = ["card_id", "series_id"]
        constraints = [
            models.UniqueConstraint(fields=["card", "series"], name="unique_card_asset")
        ]


class AssetSeries(TimeStampedModel):
    symbol = models.CharField(max_length=32, unique=True)
    label = models.CharField(max_length=64, blank=True, default="")
    timeframe = models.CharField(max_length=16, default="1m")

    class Meta:
        ordering = ["symbol"]

    def __str__(self) -> str:
        label = self.label or self.symbol
        return f"{label} ({self.timeframe})"


class AssetCandle(TimeStampedModel):
    series = models.ForeignKey(AssetSeries, on_delete=models.CASCADE, related_name="candles")
    timestamp = models.DateTimeField()
    open = models.FloatField()
    high = models.FloatField()
    low = models.FloatField()
    close = models.FloatField()
    volume = models.FloatField(default=0)

    class Meta:
        ordering = ["timestamp"]
        indexes = [models.Index(fields=["series", "timestamp"])]

    def __str__(self) -> str:
        return f"{self.series.symbol} @ {self.timestamp.isoformat()}"
