from __future__ import annotations

from datetime import timedelta

from django.utils import timezone

from articles.models import Article, HourlyBrief
from crawler.llm import LLMClient
from crawler.models import CrawlerConfig


def get_crawler_config() -> CrawlerConfig:
    config = CrawlerConfig.objects.first()
    if config is None:
        config = CrawlerConfig.objects.create()
    return config


def get_hour_window(at_time):
    start = at_time.replace(minute=0, second=0, microsecond=0)
    end = start + timedelta(hours=1)
    return start, end


def build_hourly_brief(at_time=None) -> HourlyBrief:
    now = at_time or timezone.now()
    hour_start, hour_end = get_hour_window(now)
    slug = hour_start.strftime("%Y-%m-%d-%H")
    config = get_crawler_config()

    existing = HourlyBrief.objects.filter(hour_start=hour_start).first()
    articles = list(
        Article.objects.filter(published_at__gte=hour_start, published_at__lt=hour_end)
        .order_by("-published_at")[: config.brief_max_articles]
    )
    article_count = len(articles)
    prompt = build_brief_prompt(articles, hour_start, config, existing.summary if existing else "")

    llm = LLMClient(config)
    result = llm.generate_brief(prompt) if llm.enabled else None

    if result:
        title = result.title or f"Market brief {hour_start:%H:00}"
        summary = result.summary or fallback_summary(articles)
        references = result.references or [a.url for a in articles[:5]]
    else:
        title = f"Market brief {hour_start:%H:00}"
        summary = fallback_summary(articles)
        references = [a.url for a in articles[:5]]

    brief, _ = HourlyBrief.objects.update_or_create(
        hour_start=hour_start,
        defaults={
            "hour_end": hour_end,
            "slug": slug,
            "title": title,
            "summary": summary,
            "references": references,
            "article_count": article_count,
        },
    )
    return brief


def build_brief_prompt(articles, hour_start, config: CrawlerConfig, previous_summary: str) -> str:
    lines = []
    for article in articles:
        published = article.published_at.isoformat() if article.published_at else ""
        body_snippet = (article.body or "").replace("\n", " ").strip()
        if len(body_snippet) > 280:
            body_snippet = body_snippet[:277] + "..."
        lines.append(
            "- {title} ({source}, {published})\n  URL: {url}\n  Snippet: {snippet}".format(
                title=(article.title or "Untitled").strip(),
                source=(article.source or "").strip(),
                published=published,
                url=article.url,
                snippet=body_snippet,
            )
        )

    articles_block = "\n".join(lines) or "No articles available."
    if len(articles_block) > config.brief_max_context_chars:
        articles_block = articles_block[: config.brief_max_context_chars] + "\n..."

    base_prompt = config.brief_prompt_template.format(
        articles=articles_block,
        hour_start=hour_start.isoformat(),
    )
    if previous_summary:
        base_prompt += f"\n\nPrevious summary:\n{previous_summary.strip()}\n"
    return base_prompt


def fallback_summary(articles) -> str:
    if not articles:
        return "No verified updates published in the last hour."
    summary_parts = []
    for article in articles[:5]:
        title = (article.title or "").strip()
        source = (article.source or "").strip()
        if title and source:
            summary_parts.append(f"{title} — {source}")
        else:
            summary_parts.append(title or source)
    return " · ".join([p for p in summary_parts if p]) or "No verified updates in the last hour."
