from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional

from django.conf import settings
from django.utils import timezone

from agent.models import AgentLogEvent
from articles.models import AssetCandle
from dataset.models import RawNewsItem


def prune_old_data(now: Optional[datetime] = None) -> dict[str, int]:
    """Delete rows older than the configured retention windows."""
    now = now or timezone.now()

    def cutoff(setting: str) -> datetime:
        return now - timedelta(days=int(getattr(settings, setting)))

    return {
        "logs": AgentLogEvent.objects.filter(created_at__lt=cutoff("AGENT_LOG_RETENTION_DAYS")).delete()[0],
        "raw_news": RawNewsItem.objects.filter(published_at__lt=cutoff("RAW_NEWS_RETENTION_DAYS")).delete()[0],
        "candles": AssetCandle.objects.filter(timestamp__lt=cutoff("CANDLE_RETENTION_DAYS")).delete()[0],
    }
