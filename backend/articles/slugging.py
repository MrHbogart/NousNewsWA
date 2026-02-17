from __future__ import annotations

from datetime import datetime
from uuid import UUID

from django.utils.text import slugify


def build_article_slug(
    *,
    title: str,
    period_start: datetime,
    article_uuid: UUID,
    kind: str = "main",
) -> str:
    """Build deterministic, SEO-friendly article slugs with uniqueness suffix."""
    base = slugify((title or "").strip())[:110]
    if not base:
        base = "financial-market-update" if kind == "main" else "market-detail"
    period = period_start.strftime("%Y%m%d%H%M")
    suffix = str(article_uuid).split("-")[0]
    return f"{period}-{base}-{suffix}"
