from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import re
import threading
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional
from uuid import uuid4

import httpx
from bs4 import BeautifulSoup
from dateutil import parser as dtparser
from django.conf import settings
from django.utils.text import slugify

from agent.economist_agent import EconomistAgent
from agent.llm import LLMClient
from agent.models import AgentConfig, AgentLogEvent, AgentRun, NewsSource, PriceSource
from agent.price_sync import sync_price_feeds
from articles.models import AssetSeries, Card, CardArticle, CardAsset
from articles.services import get_period_window
from articles.slugging import build_article_slug
from dataset.models import RawNewsItem


@dataclass
class AgentStats:
    pages_processed: int = 0
    articles_created: int = 0
    queued_urls: int = 0


@dataclass
class SourceSyncStats:
    sources_processed: int = 0
    items_seen: int = 0
    items_saved: int = 0
    items_rejected: int = 0


@dataclass
class SourceFetchResult:
    source_id: int
    items: list[dict]
    duration_ms: int
    error: str = ""


def get_config() -> AgentConfig:
    config = AgentConfig.objects.first()
    if config is None:
        config = AgentConfig.objects.create()
    return config


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _safe_json_value(value: object):
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {k: _safe_json_value(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_safe_json_value(v) for v in value]
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value


class AgentService:
    _MIN_RELEVANCE_SCORE = int(getattr(settings, "AGENT_MIN_RELEVANCE_SCORE", 4))
    _MAX_HOURLY_BACKFILL_HOURS = int(getattr(settings, "AGENT_MAX_HOURLY_BACKFILL_HOURS", 72))
    _MAX_AGGREGATE_BACKFILL_PERIODS = int(getattr(settings, "AGENT_MAX_AGGREGATE_BACKFILL_PERIODS", 16))
    _LLM_FILTER_SCORE_BUFFER = int(getattr(settings, "AGENT_LLM_FILTER_SCORE_BUFFER", 2))
    _LLM_FILTER_CONTEXT_CHARS = int(getattr(settings, "AGENT_LLM_FILTER_CONTEXT_CHARS", 1800))
    _LLM_MAX_REQUESTS_PER_RUN = max(0, int(getattr(settings, "AGENT_LLM_MAX_REQUESTS_PER_RUN", 2)))
    _LLM_RESERVED_FOR_ARTICLES = max(0, int(getattr(settings, "AGENT_LLM_RESERVED_FOR_ARTICLES", 2)))
    _ENABLE_ECONOMIST_AGENT = str(getattr(settings, "AGENT_ENABLE_ECONOMIST_AGENT", "false")).strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }

    _GENERIC_TITLE_SLUGS = {
        "market-brief",
        "market-update",
        "daily-market-summary",
        "daily-market-brief",
        "hourly-market-brief",
        "financial-brief",
        "financial-market-brief",
        "news-brief",
        "news-update",
        "day-market-brief",
        "week-market-brief",
        "month-market-brief",
    }

    def __init__(self, config: Optional[AgentConfig] = None):
        self.config = config or get_config()
        self.client = httpx.Client(
            timeout=getattr(settings, "AGENT_FETCH_TIMEOUT_SECONDS", 20),
            headers={"User-Agent": self.config.user_agent},
            follow_redirects=True,
        )
        self.llm = LLMClient(self.config)
        self.log_max_chars = int(getattr(settings, "AGENT_LOG_MAX_CHARS", 200000))
        self.source_fetch_workers = max(1, int(getattr(settings, "AGENT_SOURCE_FETCH_WORKERS", 8)))
        self.ingest_lookback_hours = max(1, int(getattr(settings, "AGENT_INGEST_LOOKBACK_HOURS", 24)))
        self._current_run_min_published_at: Optional[datetime] = None
        self.llm_request_budget = int(self._LLM_MAX_REQUESTS_PER_RUN)
        self.llm_reserved_for_articles = int(self._LLM_RESERVED_FOR_ARTICLES)
        self.llm_requests_used = 0
        self._llm_budget_exhausted_logged = False
        self.economist_agent_enabled = bool(self._ENABLE_ECONOMIST_AGENT)

    def close(self) -> None:
        self.client.close()

    def run(self, run: Optional[AgentRun] = None) -> AgentRun:
        run_started_at = _utc_now()
        self._current_run_min_published_at = run_started_at - timedelta(hours=self.ingest_lookback_hours)
        if run is None:
            run = AgentRun.objects.create(status=AgentRun.STATUS_RUNNING)
        elif run.status != AgentRun.STATUS_RUNNING:
            run.status = AgentRun.STATUS_RUNNING
            run.last_error = ""
            run.save(update_fields=["status", "last_error"])

        stats = AgentStats()
        self._log_event(
            run=run,
            step=AgentLogEvent.STEP_RUN_LIFECYCLE,
            message="run_started",
            metadata={
                "llm_enabled": self.llm.enabled,
                "use_llm_summaries": bool(self.config.use_llm_summaries),
                "loop_interval_minutes": self.config.loop_interval_minutes,
                "price_loop_interval_seconds": self.config.price_loop_interval_seconds,
                "ingest_lookback_hours": self.ingest_lookback_hours,
                "min_published_at": self._current_run_min_published_at,
                "llm_request_budget": self.llm_request_budget,
                "llm_reserved_for_articles": self.llm_reserved_for_articles,
                "economist_agent_enabled": self.economist_agent_enabled,
            },
        )

        try:
            fetch_stats = self._fetch_and_store_sources(run)
            stats.pages_processed = fetch_stats.sources_processed
            stats.queued_urls = fetch_stats.items_saved

            now = _utc_now()
            self._refresh_current_24h_card(run, now)
            self._refresh_current_hour_card(run, now)
            stale_finalized = self._finalize_stale_open_cards(run, now)

            hourly_created = self._finalize_due_hourly_cards(run, now)
            aggregate_created = self._finalize_due_aggregate_cards(run, now)
            stats.articles_created = stale_finalized + hourly_created + aggregate_created

            self._sync_price_feeds(run)
            run.status = AgentRun.STATUS_DONE

            duration_ms = int((_utc_now() - run_started_at).total_seconds() * 1000)
            self._log_event(
                run=run,
                step=AgentLogEvent.STEP_RUN_LIFECYCLE,
                message="run_completed",
                metadata={
                    "duration_ms": duration_ms,
                    "sources_processed": fetch_stats.sources_processed,
                    "raw_items_seen": fetch_stats.items_seen,
                    "raw_items_saved": fetch_stats.items_saved,
                    "raw_items_rejected": fetch_stats.items_rejected,
                    "cards_finalized": stats.articles_created,
                    "stale_cards_finalized": stale_finalized,
                    "hourly_cards_finalized": hourly_created,
                    "aggregate_cards_finalized": aggregate_created,
                    "llm_requests_used": self.llm_requests_used,
                    "llm_request_budget": self.llm_request_budget,
                },
            )
        except Exception as exc:
            run.status = AgentRun.STATUS_FAILED
            run.last_error = str(exc)[:2000]
            self._log_event(
                run=run,
                step=AgentLogEvent.STEP_ERROR,
                level=AgentLogEvent.LEVEL_ERROR,
                message="run_failed",
                content=str(exc),
            )
        finally:
            self._current_run_min_published_at = None
            run.pages_processed = stats.pages_processed
            run.articles_created = stats.articles_created
            run.queued_urls = stats.queued_urls
            run.ended_at = _utc_now()
            run.save(
                update_fields=[
                    "status",
                    "last_error",
                    "pages_processed",
                    "articles_created",
                    "queued_urls",
                    "ended_at",
                ]
            )
            self.close()
        return run

    def _sync_price_feeds(self, run: Optional[AgentRun]) -> None:
        try:
            stats = sync_price_feeds(user_agent=self.config.user_agent)
        except Exception as exc:
            self._log_event(
                run=run,
                step=AgentLogEvent.STEP_ERROR,
                level=AgentLogEvent.LEVEL_WARN,
                message="price_feed_sync_failed",
                content=str(exc),
            )
            return
        if stats.feeds_checked:
            self._log_event(
                run=run,
                step=AgentLogEvent.STEP_NEXT_STEP,
                message="price_feed_sync_completed",
                metadata={
                    "feeds_checked": stats.feeds_checked,
                    "items_parsed": stats.items_parsed,
                    "prices_recorded": stats.prices_recorded,
                    "api_feeds_checked": stats.api_feeds_checked,
                    "api_prices_recorded": stats.api_prices_recorded,
                },
            )

    def _build_http_client(self) -> httpx.Client:
        return httpx.Client(
            timeout=getattr(settings, "AGENT_FETCH_TIMEOUT_SECONDS", 20),
            headers={"User-Agent": self.config.user_agent},
            follow_redirects=True,
        )

    def _fetch_source_batch(self, source: NewsSource) -> SourceFetchResult:
        started = _utc_now()
        client = self._build_http_client()
        try:
            if source.source_type == NewsSource.SOURCE_API:
                items = self._fetch_api_source(source, client=client)
            else:
                items = self._fetch_rss_source(source, client=client)
            error = ""
        except Exception as exc:
            items = []
            error = str(exc)
        finally:
            client.close()
        duration_ms = int((_utc_now() - started).total_seconds() * 1000)
        return SourceFetchResult(
            source_id=source.id,
            items=items,
            duration_ms=duration_ms,
            error=error,
        )

    def _fetch_and_store_sources(self, run: AgentRun) -> SourceSyncStats:
        sources = list(NewsSource.objects.filter(enabled=True).order_by("name"))
        if not sources:
            self._log_event(
                run=run,
                step=AgentLogEvent.STEP_SOURCE_FETCH,
                level=AgentLogEvent.LEVEL_WARN,
                message="no_enabled_news_sources",
                content="Enable at least one NewsSource in Django Admin.",
            )
            return SourceSyncStats()

        stats = SourceSyncStats(sources_processed=len(sources))
        now = _utc_now()
        active_sources: list[NewsSource] = []

        for source in sources:
            if source.backoff_until and source.backoff_until > now:
                self._log_event(
                    run=run,
                    step=AgentLogEvent.STEP_SOURCE_FETCH,
                    level=AgentLogEvent.LEVEL_INFO,
                    message="source_skipped_backoff",
                    metadata={
                        "source": source.name,
                        "backoff_until": source.backoff_until,
                    },
                )
                continue

            self._log_event(
                run=run,
                step=AgentLogEvent.STEP_SOURCE_FETCH,
                message="source_fetch_started",
                metadata={
                    "source": source.name,
                    "source_type": source.source_type,
                    "source_url": source.base_url,
                },
            )
            active_sources.append(source)

        if not active_sources:
            return stats

        workers = max(1, min(len(active_sources), self.source_fetch_workers))
        with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="news-source") as executor:
            futures = {
                executor.submit(self._fetch_source_batch, source): source
                for source in active_sources
            }
            for future in as_completed(futures):
                source = futures[future]
                try:
                    fetched = future.result()
                except Exception as exc:
                    fetched = SourceFetchResult(
                        source_id=source.id,
                        items=[],
                        duration_ms=0,
                        error=str(exc),
                    )

                if fetched.error:
                    if fetched.error == "rate_limited":
                        self._apply_backoff(source, "rate_limited")
                    else:
                        self._record_source_error(source, fetched.error)
                    self._log_event(
                        run=run,
                        step=AgentLogEvent.STEP_SOURCE_FETCH,
                        level=AgentLogEvent.LEVEL_WARN,
                        message="source_fetch_failed",
                        content=fetched.error,
                        metadata={
                            "source": source.name,
                            "source_url": source.base_url,
                            "duration_ms": fetched.duration_ms,
                        },
                    )
                    continue

                seen_keys = set()
                source_latest: Optional[datetime] = None
                source_seen = 0
                source_saved = 0
                source_rejected = 0
                source_rejected_old = 0
                source_rejected_llm = 0

                for item in fetched.items:
                    source_seen += 1
                    stats.items_seen += 1

                    title = (item.get("title") or "").strip()
                    summary = (item.get("summary") or "").strip()
                    content = (item.get("content") or "").strip()
                    raw_text = content or summary or title
                    cleaned = self._clean_text(raw_text)
                    if not cleaned:
                        source_rejected += 1
                        stats.items_rejected += 1
                        continue

                    published_dt = self._parse_datetime(item.get("published_at"))
                    if not published_dt:
                        source_rejected += 1
                        stats.items_rejected += 1
                        continue
                    if self._current_run_min_published_at and published_dt < self._current_run_min_published_at:
                        source_rejected += 1
                        source_rejected_old += 1
                        stats.items_rejected += 1
                        continue

                    score = self._relevance_score(cleaned, title)
                    llm_filter = None
                    if self._should_apply_llm_filter(run, score):
                        llm_filter = self._llm_filter_decision(
                            title=title,
                            summary=summary,
                            content=cleaned,
                            heuristic_score=score,
                            run=run,
                            source_name=source.name,
                            source_url=source.base_url,
                            item_url=(item.get("url") or "").strip(),
                        )
                    if llm_filter is not None and not llm_filter.get("accepted", False):
                        source_rejected += 1
                        source_rejected_llm += 1
                        stats.items_rejected += 1
                        continue
                    if score < self._MIN_RELEVANCE_SCORE and not (llm_filter and llm_filter.get("accepted", False)):
                        source_rejected += 1
                        stats.items_rejected += 1
                        continue

                    dedupe_key = self._dedupe_key(item, title, published_dt)
                    if dedupe_key in seen_keys:
                        source_rejected += 1
                        stats.items_rejected += 1
                        continue
                    seen_keys.add(dedupe_key)

                    normalized = {
                        "title": title,
                        "summary": summary,
                        "content": content,
                        "url": (item.get("url") or "").strip(),
                        "published_at": published_dt,
                    }
                    self._store_raw_item(source, normalized, cleaned)
                    source_saved += 1
                    stats.items_saved += 1

                    if source_latest is None or published_dt > source_latest:
                        source_latest = published_dt

                source.last_fetched_at = source_latest or now
                source.failure_count = 0
                source.last_error = ""
                source.backoff_until = None
                source.save(update_fields=["last_fetched_at", "failure_count", "last_error", "backoff_until"])

                self._log_event(
                    run=run,
                    step=AgentLogEvent.STEP_SOURCE_FETCH,
                    message="source_fetch_completed",
                    metadata={
                        "source": source.name,
                        "items_seen": source_seen,
                        "items_saved": source_saved,
                        "items_rejected": source_rejected,
                        "items_rejected_old": source_rejected_old,
                        "items_rejected_llm": source_rejected_llm,
                        "min_published_at": self._current_run_min_published_at,
                        "duration_ms": fetched.duration_ms,
                    },
                )

        return stats

    def _finalize_stale_open_cards(self, run: AgentRun, now: datetime) -> int:
        stale_cards = list(
            Card.objects.filter(status=Card.STATUS_OPEN, period_end__lte=now)
            .exclude(timeframe=Card.TIMEFRAME_HOUR)
            .order_by("period_start")
            .prefetch_related("articles")
        )
        finalized = 0
        for card in stale_cards:
            main = next((a for a in card.articles.all() if a.kind == CardArticle.KIND_MAIN), None)
            if main is None and (card.title or card.summary or card.body):
                fallback_payload = {
                    "title": self._ensure_informative_title(card.title, [], card.timeframe, card.period_start),
                    "summary": (card.summary or "").strip(),
                    "body": (card.body or "").strip(),
                    "references": self._normalize_references(card.references),
                    "impacts": [],
                    "importance_score": self._normalize_importance_score(card.importance_score) or 1,
                    "importance_reason": (card.importance_reason or "").strip(),
                }
                self._upsert_card_articles(card=card, main_payload=fallback_payload, side_payloads=[])
            card.status = Card.STATUS_FINAL
            card.save(update_fields=["status"])
            finalized += 1
            self._log_event(
                run=run,
                step=AgentLogEvent.STEP_CARD_GENERATION,
                message="stale_open_card_finalized",
                metadata={
                    "timeframe": card.timeframe,
                    "period_start": card.period_start,
                    "period_end": card.period_end,
                    "slug": card.slug,
                },
            )
        return finalized

    def _current_rolling_day_window(self, now: datetime) -> tuple[datetime, datetime]:
        current_hour_start = now.replace(minute=0, second=0, microsecond=0)
        period_end = current_hour_start + timedelta(hours=1)
        period_start = period_end - timedelta(hours=24)
        return period_start, period_end

    def _refresh_current_24h_card(self, run: AgentRun, now: datetime) -> None:
        period_start, period_end = self._current_rolling_day_window(now)
        existing = Card.objects.filter(
            timeframe=Card.TIMEFRAME_DAY,
            period_start=period_start,
        ).first()
        if existing and existing.status == Card.STATUS_FINAL:
            return

        records = self._load_raw_records(period_start, min(now, period_end))
        if not records:
            return

        card = self._get_or_create_open_card_for_period(Card.TIMEFRAME_DAY, period_start, period_end)
        source_label = ", ".join(dict.fromkeys([r.get("source_name") or "" for r in records if r.get("source_name")]))[:255]
        published_at = max((r.get("published_at") for r in records if r.get("published_at")), default=now)
        if existing and existing.status == Card.STATUS_OPEN:
            same_count = int(existing.article_count or 0) == len(records)
            same_or_newer_pub = bool(existing.published_at and published_at and existing.published_at >= published_at)
            if same_count and same_or_newer_pub and (existing.title or existing.summary or existing.body):
                self._log_event(
                    run=run,
                    step=AgentLogEvent.STEP_CARD_GENERATION,
                    message="current_24h_card_unchanged_skipped",
                    metadata={
                        "period_start": period_start,
                        "period_end": period_end,
                        "item_count": len(records),
                        "card_slug": existing.slug,
                    },
                )
                return

        main_payload = self._build_main_payload(
            records=records,
            timeframe=Card.TIMEFRAME_DAY,
            period_start=period_start,
            period_end=period_end,
            run=run,
        )
        side_payloads = self._build_side_articles(records)

        card.published_at = published_at
        self._upsert_card_articles(card=card, main_payload=main_payload, side_payloads=side_payloads)

        card.title = main_payload["title"]
        card.summary = main_payload["summary"]
        card.body = main_payload["body"]
        card.references = main_payload["references"]
        card.importance_score = main_payload["importance_score"]
        card.importance_reason = main_payload["importance_reason"]
        card.source_name = source_label
        card.published_at = published_at
        card.article_count = len(records)
        card.status = Card.STATUS_OPEN
        card.save(
            update_fields=[
                "title",
                "summary",
                "body",
                "references",
                "importance_score",
                "importance_reason",
                "source_name",
                "published_at",
                "article_count",
                "status",
            ]
        )
        self._ensure_card_assets(card)
        self._log_event(
            run=run,
            step=AgentLogEvent.STEP_CARD_GENERATION,
            message="current_24h_card_refreshed",
            metadata={
                "period_start": period_start,
                "period_end": period_end,
                "item_count": len(records),
                "card_slug": card.slug,
                "article_slug": main_payload.get("slug"),
                "title": card.title,
                "status": card.status,
            },
        )

    def _refresh_current_hour_card(self, run: AgentRun, now: datetime) -> None:
        period_start = now.replace(minute=0, second=0, microsecond=0)
        period_end = period_start + timedelta(hours=1)

        existing = Card.objects.filter(
            timeframe=Card.TIMEFRAME_HOUR,
            period_start=period_start,
        ).first()
        if existing and existing.status == Card.STATUS_FINAL:
            return

        records = self._load_raw_records(period_start, min(now, period_end))
        if not records:
            return

        card = self._get_or_create_open_card_for_period(Card.TIMEFRAME_HOUR, period_start, period_end)
        source_label = ", ".join(dict.fromkeys([r.get("source_name") or "" for r in records if r.get("source_name")]))[:255]
        published_at = max((r.get("published_at") for r in records if r.get("published_at")), default=now)
        if existing and existing.status == Card.STATUS_OPEN:
            same_count = int(existing.article_count or 0) == len(records)
            same_or_newer_pub = bool(existing.published_at and published_at and existing.published_at >= published_at)
            if same_count and same_or_newer_pub and (existing.title or existing.summary or existing.body):
                self._log_event(
                    run=run,
                    step=AgentLogEvent.STEP_CARD_GENERATION,
                    message="current_hour_card_unchanged_skipped",
                    metadata={
                        "period_start": period_start,
                        "period_end": period_end,
                        "item_count": len(records),
                        "card_slug": existing.slug,
                    },
                )
                return

        main_payload = self._build_main_payload(
            records=records,
            timeframe=Card.TIMEFRAME_HOUR,
            period_start=period_start,
            period_end=period_end,
            run=run,
        )
        side_payloads = self._build_side_articles(records)

        card.published_at = published_at
        self._upsert_card_articles(card=card, main_payload=main_payload, side_payloads=side_payloads)

        card.title = main_payload["title"]
        card.summary = main_payload["summary"]
        card.body = main_payload["body"]
        card.references = main_payload["references"]
        card.importance_score = main_payload["importance_score"]
        card.importance_reason = main_payload["importance_reason"]
        card.source_name = source_label
        card.published_at = published_at
        card.article_count = len(records)
        card.status = Card.STATUS_OPEN
        card.save(
            update_fields=[
                "title",
                "summary",
                "body",
                "references",
                "importance_score",
                "importance_reason",
                "source_name",
                "published_at",
                "article_count",
                "status",
            ]
        )
        self._ensure_card_assets(card)
        self._log_event(
            run=run,
            step=AgentLogEvent.STEP_CARD_GENERATION,
            message="current_hour_card_refreshed",
            metadata={
                "period_start": period_start,
                "period_end": period_end,
                "item_count": len(records),
                "card_slug": card.slug,
                "article_slug": main_payload.get("slug"),
                "title": card.title,
                "status": card.status,
            },
        )

    def _finalize_due_hourly_cards(self, run: AgentRun, now: datetime) -> int:
        latest_closed_start = now.replace(minute=0, second=0, microsecond=0) - timedelta(hours=1)
        if latest_closed_start.year < 2000:
            return 0

        starts = self._due_period_starts(Card.TIMEFRAME_HOUR, latest_closed_start)
        if not starts:
            self._log_event(
                run=run,
                step=AgentLogEvent.STEP_CARD_GENERATION,
                message="no_due_hourly_periods",
                metadata={"latest_closed_start": latest_closed_start},
            )
            return 0

        finalized = 0
        for period_start in starts:
            period_end = period_start + timedelta(hours=1)
            existing = Card.objects.filter(
                timeframe=Card.TIMEFRAME_HOUR,
                period_start=period_start,
                status=Card.STATUS_FINAL,
            ).first()
            if existing and existing.articles.filter(kind=CardArticle.KIND_MAIN).exists():
                continue

            records = self._load_raw_records(period_start, period_end)
            if not records:
                continue

            card = self._get_or_create_card_for_period(Card.TIMEFRAME_HOUR, period_start, period_end)
            source_label = ", ".join(dict.fromkeys([r.get("source_name") or "" for r in records if r.get("source_name")]))[:255]
            published_at = max((r.get("published_at") for r in records if r.get("published_at")), default=period_end)
            main_payload = self._build_main_payload(
                records=records,
                timeframe=Card.TIMEFRAME_HOUR,
                period_start=period_start,
                period_end=period_end,
                run=run,
            )
            side_payloads = self._build_side_articles(records)
            card.published_at = published_at
            self._upsert_card_articles(card=card, main_payload=main_payload, side_payloads=side_payloads)

            card.title = main_payload["title"]
            card.summary = main_payload["summary"]
            card.body = main_payload["body"]
            card.references = main_payload["references"]
            card.importance_score = main_payload["importance_score"]
            card.importance_reason = main_payload["importance_reason"]
            card.source_name = source_label
            card.published_at = published_at
            card.article_count = len(records)
            card.status = Card.STATUS_FINAL
            card.save(
                update_fields=[
                    "title",
                    "summary",
                    "body",
                    "references",
                    "importance_score",
                    "importance_reason",
                    "source_name",
                    "published_at",
                    "article_count",
                    "status",
                ]
            )
            self._ensure_card_assets(card)
            finalized += 1

            self._log_event(
                run=run,
                step=AgentLogEvent.STEP_CARD_GENERATION,
                message="hourly_card_finalized",
                metadata={
                    "period_start": period_start,
                    "period_end": period_end,
                    "item_count": len(records),
                    "card_slug": card.slug,
                    "article_slug": main_payload.get("slug"),
                    "title": card.title,
                },
            )

        return finalized

    def _finalize_due_aggregate_cards(self, run: AgentRun, now: datetime) -> int:
        total_finalized = 0
        for timeframe in (Card.TIMEFRAME_WEEK, Card.TIMEFRAME_MONTH):
            latest_closed_start = self._latest_closed_period_start(timeframe, now)
            if latest_closed_start is None:
                continue
            starts = self._due_period_starts(timeframe, latest_closed_start)
            for period_start in starts:
                period_end = self._next_period_start(timeframe, period_start)
                existing = Card.objects.filter(
                    timeframe=timeframe,
                    period_start=period_start,
                    status=Card.STATUS_FINAL,
                ).first()
                if existing and existing.articles.filter(kind=CardArticle.KIND_MAIN).exists():
                    continue

                records = self._load_raw_records(period_start, period_end)
                if not records:
                    continue
                total_items = len(records)
                source_label = ", ".join(
                    dict.fromkeys([r.get("source_name") or "" for r in records if r.get("source_name")])
                )[:255]

                card = self._get_or_create_card_for_period(timeframe, period_start, period_end)
                published_at = max((r.get("published_at") for r in records if r.get("published_at")), default=period_end)
                main_payload = self._build_main_payload(
                    records=records,
                    timeframe=timeframe,
                    period_start=period_start,
                    period_end=period_end,
                    run=run,
                )
                side_payloads = self._build_side_articles(records)

                card.published_at = published_at
                self._upsert_card_articles(card=card, main_payload=main_payload, side_payloads=side_payloads)

                card.title = main_payload["title"]
                card.summary = main_payload["summary"]
                card.body = main_payload["body"]
                card.references = main_payload["references"]
                card.importance_score = main_payload["importance_score"]
                card.importance_reason = main_payload["importance_reason"]
                card.source_name = source_label
                card.published_at = published_at
                card.article_count = total_items
                card.status = Card.STATUS_FINAL
                card.save(
                    update_fields=[
                        "title",
                        "summary",
                        "body",
                        "references",
                        "importance_score",
                        "importance_reason",
                        "source_name",
                        "published_at",
                        "article_count",
                        "status",
                    ]
                )
                self._ensure_card_assets(card)
                total_finalized += 1

                self._log_event(
                    run=run,
                    step=AgentLogEvent.STEP_CARD_GENERATION,
                    message="aggregate_card_finalized",
                    metadata={
                        "timeframe": timeframe,
                        "period_start": period_start,
                        "period_end": period_end,
                        "hourly_records": len(records),
                        "source_items": total_items,
                        "card_slug": card.slug,
                        "article_slug": main_payload.get("slug"),
                        "title": card.title,
                    },
                )

        return total_finalized

    def _build_main_payload(
        self,
        *,
        records: list[dict],
        timeframe: str,
        period_start: datetime,
        period_end: datetime,
        run: Optional[AgentRun],
    ) -> dict:
        fallback = self._compose_fallback_payload(records, timeframe, period_start, period_end)
        context = self._build_context_from_records(records, timeframe=timeframe)

        generated_title = ""
        generated_summary = ""
        generated_body = ""
        generated_impacts = []
        generated_references: list[str] = []
        generated_importance_score: Optional[int] = None
        generated_importance_reason = ""

        if self.config.use_llm_summaries and self.llm.enabled and context:
            prompt = self._build_article_prompt(context, timeframe, period_start, period_end)
            result = None
            if self._consume_llm_budget(run=run, purpose="article_generation", reserve=0):
                self._log_event(
                    run=run,
                    step=AgentLogEvent.STEP_LLM_PROMPT,
                    message="article_prompt_prepared",
                    content=prompt,
                    metadata={
                        "timeframe": timeframe,
                        "period_start": period_start,
                        "period_end": period_end,
                        "records": len(records),
                        "prompt_chars": len(prompt),
                    },
                )

                result = self.llm.generate_article(prompt)
                self._log_event(
                    run=run,
                    step=AgentLogEvent.STEP_LLM_OUTPUT,
                    message="article_prompt_completed",
                    content=self.llm.last_output_text or "",
                    metadata={
                        "status_code": self.llm.last_status_code,
                        "error": self.llm.last_error,
                        "model": self.llm.last_model,
                        "output_chars": len(self.llm.last_output_text or ""),
                        "parsed": bool(result),
                    },
                )
            else:
                self._log_event(
                    run=run,
                    step=AgentLogEvent.STEP_NEXT_STEP,
                    level=AgentLogEvent.LEVEL_WARN,
                    message="article_prompt_skipped_budget",
                    metadata={
                        "timeframe": timeframe,
                        "period_start": period_start,
                        "period_end": period_end,
                        "records": len(records),
                        "llm_requests_used": self.llm_requests_used,
                        "llm_request_budget": self.llm_request_budget,
                    },
                )

            if result:
                generated_title = result.title or ""
                generated_summary = result.summary or ""
                generated_body = result.article_text or ""
                generated_impacts = result.impacts or []
                generated_references = self._normalize_references(result.references)
                generated_importance_score = self._normalize_importance_score(result.importance_score)
                generated_importance_reason = (result.importance_reason or "").strip()

            economist_output = None
            if self.economist_agent_enabled and self._llm_budget_remaining() > 0:
                economist_output = EconomistAgent(
                    self.llm,
                    generate_json_fn=lambda p: self._budgeted_generate_json(
                        p,
                        run=run,
                        purpose="economist_rewrite",
                    ),
                ).run(context)
            writing = (economist_output or {}).get("writing") if economist_output else None
            trace = (economist_output or {}).get("trace") if economist_output else None
            if trace:
                if trace.get("signals_prompt"):
                    self._log_event(
                        run=run,
                        step=AgentLogEvent.STEP_LLM_PROMPT,
                        message="economist_signals_prompt_prepared",
                        content=trace.get("signals_prompt") or "",
                        metadata={
                            "timeframe": timeframe,
                            "period_start": period_start,
                            "period_end": period_end,
                        },
                    )
                if trace.get("signals_output"):
                    self._log_event(
                        run=run,
                        step=AgentLogEvent.STEP_LLM_OUTPUT,
                        message="economist_signals_prompt_completed",
                        content=trace.get("signals_output") or "",
                        metadata={
                            "timeframe": timeframe,
                            "period_start": period_start,
                            "period_end": period_end,
                        },
                    )
                if trace.get("writing_prompt"):
                    self._log_event(
                        run=run,
                        step=AgentLogEvent.STEP_LLM_PROMPT,
                        message="economist_writing_prompt_prepared",
                        content=trace.get("writing_prompt") or "",
                        metadata={
                            "timeframe": timeframe,
                            "period_start": period_start,
                            "period_end": period_end,
                        },
                    )
                if trace.get("writing_output"):
                    self._log_event(
                        run=run,
                        step=AgentLogEvent.STEP_LLM_OUTPUT,
                        message="economist_writing_prompt_completed",
                        content=trace.get("writing_output") or "",
                        metadata={
                            "timeframe": timeframe,
                            "period_start": period_start,
                            "period_end": period_end,
                        },
                    )
            if writing:
                generated_title = writing.get("article_title") or generated_title
                generated_summary = writing.get("summary") or generated_summary
                generated_body = writing.get("article_text") or generated_body
                generated_references = self._normalize_references(writing.get("references") or generated_references)
                generated_importance_score = (
                    self._normalize_importance_score(writing.get("importance_score"))
                    or generated_importance_score
                )
                generated_importance_reason = (
                    (writing.get("importance_reason") or "").strip()
                    or generated_importance_reason
                )

        clean_generated_title = self._sanitize_generated_text(generated_title, keep_paragraphs=False)
        clean_generated_summary = self._sanitize_generated_text(generated_summary, keep_paragraphs=False)
        clean_generated_body = self._sanitize_generated_text(generated_body, keep_paragraphs=True)

        title = self._ensure_informative_title(clean_generated_title, records, timeframe, period_start)
        if self._is_generic_title(title):
            title = fallback["title"]

        summary = self._strip_time_window_phrasing(clean_generated_summary) or fallback["summary"]
        if len(summary) > 600:
            summary = summary[:597].rstrip() + "..."

        cleaned_generated_body = self._strip_time_window_phrasing(clean_generated_body)
        body = self._ensure_complete_article(cleaned_generated_body, fallback["body"])
        impacts = generated_impacts if isinstance(generated_impacts, list) and generated_impacts else fallback["impacts"]
        references = self._normalize_references(generated_references or fallback["references"])
        importance_score = generated_importance_score or fallback["importance_score"]
        importance_reason = self._compact_text(generated_importance_reason, 280) or fallback["importance_reason"]

        slug = build_article_slug(
            title=title,
            period_start=period_start,
            article_uuid=uuid4(),
            kind=CardArticle.KIND_MAIN,
        )

        return {
            "title": title,
            "summary": summary,
            "body": body,
            "references": references,
            "impacts": impacts,
            "importance_score": importance_score,
            "importance_reason": importance_reason,
            "slug": slug,
        }

    def _compose_fallback_payload(
        self,
        records: list[dict],
        timeframe: str,
        period_start: datetime,
        period_end: datetime,
    ) -> dict:
        ranked = sorted(
            records,
            key=lambda item: item.get("published_at") or datetime.min.replace(tzinfo=timezone.utc),
            reverse=True,
        )

        title = self._ensure_informative_title("", ranked, timeframe, period_start)
        intro = (
            f"{len(ranked)} financially relevant developments were identified across tracked market sources, "
            "with clear implications for cross-asset positioning."
        )

        detail_sentences = []
        for item in ranked[:4]:
            headline = self._compact_text(item.get("title") or item.get("summary") or item.get("content") or "", 180)
            if not headline:
                continue
            source_name = item.get("source_name") or "newswire"
            detail_sentences.append(
                f"{source_name} reported {headline}. {self._impact_sentence(item)}"
            )

        if not detail_sentences:
            detail_sentences.append(
                "No lower-impact or off-topic items were included; this brief is restricted to market-moving records only."
            )

        closing = (
            "Taken together, these signals can influence rate expectations, risk appetite, "
            "currency positioning, and sector-level equity rotation in the next trading sessions."
        )

        body = "\n\n".join([intro] + detail_sentences + [closing])
        summary = " ".join([intro] + detail_sentences[:2])
        summary = self._compact_text(summary, 600)

        impacts = self._derive_impacts(ranked)
        references = self._normalize_references([item.get("url") for item in ranked if item.get("url")])
        importance_score, importance_reason = self._infer_importance_from_records(
            ranked,
            title=title,
            summary=summary,
            body=body,
        )

        return {
            "title": title,
            "summary": summary,
            "body": body,
            "impacts": impacts,
            "references": references,
            "importance_score": importance_score,
            "importance_reason": importance_reason,
        }

    def _impact_sentence(self, record: dict) -> str:
        text = (record.get("title") or "") + " " + (record.get("summary") or "") + " " + (record.get("content") or "")
        low = text.lower()
        if any(token in low for token in ["interest rate", "fed", "ecb", "inflation", "cpi", "ppi", "gdp"]):
            return "This type of catalyst typically reprices rates markets and policy-sensitive FX pairs."
        if any(token in low for token in ["earnings", "guidance", "revenue", "profit", "m&a", "merger", "acquisition"]):
            return "This development is likely to affect equity valuation multiples and sector positioning."
        if any(token in low for token in ["oil", "gas", "commodity", "energy", "supply chain", "tariff", "sanction"]):
            return "Commodity-linked inflation expectations and regional risk premia could adjust quickly."
        if any(token in low for token in ["bond", "yield", "treasury", "credit", "default", "rating"]):
            return "Credit spreads and sovereign yield curves may react as investors reprice risk."
        return "Cross-asset positioning may adjust as participants incorporate the new information into risk scenarios."

    def _derive_impacts(self, records: list[dict]) -> list[str]:
        low = " ".join(
            [
                (item.get("title") or "") + " " + (item.get("summary") or "") + " " + (item.get("content") or "")
                for item in records
            ]
        ).lower()

        impacts = []
        if any(token in low for token in ["interest rate", "fed", "ecb", "inflation", "cpi", "ppi", "gdp"]):
            impacts.append("Rates and FX: policy expectations can reprice sovereign yields and major currency pairs.")
        if any(token in low for token in ["earnings", "guidance", "revenue", "profit", "m&a", "merger", "acquisition"]):
            impacts.append("Equities: sector rotation risk rises as earnings and corporate actions reshape valuation assumptions.")
        if any(token in low for token in ["oil", "gas", "commodity", "energy", "supply chain", "tariff", "sanction"]):
            impacts.append("Commodities: supply and geopolitics can amplify volatility in energy and input-sensitive sectors.")
        if any(token in low for token in ["bond", "yield", "treasury", "credit", "default", "rating"]):
            impacts.append("Credit: spread widening risk can pressure leveraged balance sheets and higher-beta assets.")
        if not impacts:
            impacts.append("Risk sentiment: cross-asset positioning may shift as new macro information is priced in.")
        return impacts[:6]

    def _build_context_from_records(self, records: list[dict], *, timeframe: str) -> str:
        chunks = []
        for item in records:
            title = (item.get("title") or "").strip()
            summary = (item.get("summary") or "").strip()
            content = (item.get("cleaned_text") or item.get("content") or "").strip()
            source = (item.get("source_name") or "unknown").strip()
            url = (item.get("url") or "").strip()
            piece = f"({source}) {title}\nSummary: {summary}\nDetails: {content}\nURL: {url}"
            chunks.append(piece)
        combined = "\n\n".join(chunks)
        if timeframe in (Card.TIMEFRAME_HOUR, Card.TIMEFRAME_DAY):
            return combined
        max_chars = int(self.config.max_context_chars or 0)
        if max_chars > 0:
            combined = combined[:max_chars]
        return combined

    def _build_side_articles(self, records: list[dict]) -> list[dict]:
        ranked = sorted(
            records,
            key=lambda item: item.get("published_at") or datetime.min.replace(tzinfo=timezone.utc),
            reverse=True,
        )
        payloads = []
        for entry in ranked[1:3]:
            title = self._compact_text(
                self._sanitize_generated_text(entry.get("title") or entry.get("summary") or "Market update"),
                120,
            )
            summary = self._compact_text(
                self._sanitize_generated_text(entry.get("summary") or entry.get("content") or ""),
                420,
            )
            body = self._compact_text(
                self._sanitize_generated_text(entry.get("content") or summary, keep_paragraphs=True),
                1300,
            )
            payloads.append(
                {
                    "title": title,
                    "summary": summary,
                    "body": body,
                    "references": self._normalize_references([entry.get("url")]),
                    "published_at": entry.get("published_at"),
                }
            )
        return payloads

    def _sanitize_generated_text(self, text: str, *, keep_paragraphs: bool = False) -> str:
        raw = (text or "").strip()
        if not raw:
            return ""

        # Some models wrap text in markdown code fences when formatting drifts.
        raw = re.sub(r"^\s*```(?:json|markdown|md|text|html)?\s*", "", raw, flags=re.IGNORECASE)
        raw = re.sub(r"\s*```\s*$", "", raw, flags=re.IGNORECASE)

        soup = BeautifulSoup(raw, "html.parser")
        for tag in soup(["script", "style", "noscript", "iframe", "object", "embed"]):
            tag.decompose()
        for node in soup.select("blockquote.twitter-tweet, blockquote.instagram-media, blockquote.tiktok-embed"):
            node.decompose()

        extracted = soup.get_text("\n" if keep_paragraphs else " ")
        if keep_paragraphs:
            extracted = extracted.replace("\xa0", " ")
            extracted = extracted.replace("\r\n", "\n").replace("\r", "\n")
            extracted = "\n".join(line.strip() for line in extracted.split("\n"))
            extracted = re.sub(r"\n{3,}", "\n\n", extracted)
            return extracted.strip()

        extracted = extracted.replace("\xa0", " ")
        return re.sub(r"\s+", " ", extracted).strip()

    def _ensure_complete_article(self, candidate: str, fallback: str) -> str:
        text = self._sanitize_generated_text(candidate or "", keep_paragraphs=True)
        fallback_clean = self._sanitize_generated_text(fallback or "", keep_paragraphs=True)
        if text:
            sentence_count = len([s for s in re.split(r"[.!?]+", text) if s.strip()])
            word_count = len(text.split())
            if sentence_count >= 4 and word_count >= 80:
                return text
        return fallback_clean

    def _strip_time_window_phrasing(self, text: str) -> str:
        cleaned = (text or "").strip()
        if not cleaned:
            return ""

        replacements = [
            (r"\b(in|during)\s+this\s+(time\s+window|window|period|hour)\b[:,]?\s*", ""),
            (r"\bat\s+this\s+time\b[:,]?\s*", ""),
            (r"\bfor\s+the\s+current\s+time\s+window\b[:,]?\s*", ""),
            (r"\bwithin\s+this\s+(time\s+window|period)\b[:,]?\s*", ""),
            (r"\bthese\s+news\s+were\s+published\b[:,]?\s*", ""),
        ]
        for pattern, replacement in replacements:
            cleaned = re.sub(pattern, replacement, cleaned, flags=re.IGNORECASE)

        cleaned = re.sub(r"\s{2,}", " ", cleaned)
        cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
        return cleaned.strip()

    def _ensure_informative_title(
        self,
        candidate: str,
        records: list[dict],
        timeframe: str,
        period_start: datetime,
    ) -> str:
        value = self._compact_text(candidate or "", 140)
        if value and not self._is_generic_title(value):
            return value

        ranked = sorted(
            records,
            key=lambda item: item.get("published_at") or datetime.min.replace(tzinfo=timezone.utc),
            reverse=True,
        )

        for item in ranked:
            headline = self._compact_text(item.get("title") or item.get("summary") or "", 120)
            if headline and not self._is_generic_title(headline):
                return headline

        if timeframe == Card.TIMEFRAME_HOUR:
            return f"Financial Market Impact Update for {period_start.strftime('%Y-%m-%d %H:00 UTC')}"
        if timeframe == Card.TIMEFRAME_DAY:
            period_end = period_start + timedelta(hours=24)
            return (
                "24-Hour Financial Market Impact Summary ending "
                f"{period_end.strftime('%Y-%m-%d %H:00 UTC')}"
            )
        if timeframe == Card.TIMEFRAME_WEEK:
            return f"Weekly Financial Market Impact Summary for Week of {period_start.strftime('%Y-%m-%d')}"
        return f"Monthly Financial Market Impact Summary for {period_start.strftime('%B %Y')}"

    def _is_generic_title(self, value: str) -> bool:
        slug = slugify((value or "").strip())
        if not slug:
            return True
        if slug in self._GENERIC_TITLE_SLUGS:
            return True
        if slug.startswith("market-brief") or slug.endswith("market-brief"):
            return True
        if slug.startswith("market-update") or slug.endswith("market-update"):
            return True
        return False

    @staticmethod
    def _compact_text(text: str, limit: int) -> str:
        value = re.sub(r"\s+", " ", (text or "").strip())
        if len(value) <= limit:
            return value
        clipped = value[:limit].rstrip()
        if " " in clipped:
            clipped = clipped.rsplit(" ", 1)[0]
        return clipped.rstrip(".,;: ") + "..."

    def _load_raw_records(self, start: datetime, end: datetime) -> list[dict]:
        qs = RawNewsItem.objects.filter(published_at__gte=start, published_at__lt=end).order_by("-published_at")
        records = []
        seen = set()
        for raw in qs:
            cleaned = raw.cleaned_text or self._clean_text(raw.content or raw.summary or raw.title)
            score = self._relevance_score(cleaned, raw.title or "")
            if score < self._MIN_RELEVANCE_SCORE:
                continue
            key = self._dedupe_key({"url": raw.url}, raw.title, raw.published_at)
            if key in seen:
                continue
            seen.add(key)
            records.append(
                {
                    "source_name": raw.source_name,
                    "title": raw.title,
                    "summary": raw.summary,
                    "content": raw.content,
                    "cleaned_text": cleaned,
                    "url": raw.url,
                    "published_at": raw.published_at,
                }
            )
        return records

    def _load_hourly_records(self, start: datetime, end: datetime) -> tuple[list[dict], int, str]:
        hourly_cards = (
            Card.objects.filter(
                timeframe=Card.TIMEFRAME_HOUR,
                status=Card.STATUS_FINAL,
                period_start__gte=start,
                period_start__lt=end,
            )
            .order_by("period_start")
            .prefetch_related("articles")
        )

        records = []
        total_items = 0
        sources: list[str] = []
        for card in hourly_cards:
            main = next((article for article in card.articles.all() if article.kind == CardArticle.KIND_MAIN), None)
            if main is None:
                continue
            text = (main.body or main.summary or "").strip()
            if not text:
                continue
            first_ref = ""
            if isinstance(main.references, list) and main.references:
                first_ref = str(main.references[0])
            records.append(
                {
                    "source_name": card.source_name or "aggregated hourly brief",
                    "title": main.title,
                    "summary": main.summary,
                    "content": text,
                    "cleaned_text": text,
                    "url": first_ref,
                    "published_at": card.published_at or card.period_end,
                }
            )
            total_items += int(card.article_count or 0)
            if card.source_name:
                sources.append(card.source_name)

        source_label = ", ".join(dict.fromkeys(sources))[:255]
        return records, total_items, source_label

    def _due_period_starts(self, timeframe: str, latest_closed_start: datetime) -> list[datetime]:
        last_final = (
            Card.objects.filter(
                timeframe=timeframe,
                status=Card.STATUS_FINAL,
                period_start__lte=latest_closed_start,
            )
            .order_by("-period_start")
            .first()
        )
        if last_final:
            cursor = self._next_period_start(timeframe, last_final.period_start)
        else:
            if timeframe == Card.TIMEFRAME_HOUR:
                earliest = RawNewsItem.objects.filter(published_at__isnull=False).order_by("published_at").first()
                if not earliest or not earliest.published_at:
                    return []
                cursor = earliest.published_at.replace(minute=0, second=0, microsecond=0)
            else:
                earliest_hour = (
                    Card.objects.filter(timeframe=Card.TIMEFRAME_HOUR, status=Card.STATUS_FINAL)
                    .order_by("period_start")
                    .first()
                )
                if earliest_hour is None:
                    earliest_hour = Card.objects.filter(timeframe=Card.TIMEFRAME_HOUR).order_by("period_start").first()
                if not earliest_hour:
                    return []
                cursor, _ = get_period_window(earliest_hour.period_start, timeframe)

        if timeframe == Card.TIMEFRAME_HOUR:
            lower_bound = latest_closed_start - timedelta(hours=max(1, self._MAX_HOURLY_BACKFILL_HOURS - 1))
            if cursor < lower_bound:
                cursor = lower_bound

        starts = []
        while cursor <= latest_closed_start:
            starts.append(cursor)
            cursor = self._next_period_start(timeframe, cursor)
        if timeframe != Card.TIMEFRAME_HOUR and len(starts) > self._MAX_AGGREGATE_BACKFILL_PERIODS:
            starts = starts[-self._MAX_AGGREGATE_BACKFILL_PERIODS :]
        return starts

    def _latest_closed_period_start(self, timeframe: str, now: datetime) -> Optional[datetime]:
        current_start, _ = get_period_window(now, timeframe)
        probe = current_start - timedelta(seconds=1)
        if probe.year < 2000:
            return None
        closed_start, _ = get_period_window(probe, timeframe)
        return closed_start

    def _next_period_start(self, timeframe: str, start: datetime) -> datetime:
        _, end = get_period_window(start, timeframe)
        return end

    def _get_or_create_card_for_period(self, timeframe: str, start: datetime, end: datetime) -> Card:
        slug = self._card_slug(timeframe, start)
        defaults = {"period_end": end, "slug": slug, "status": Card.STATUS_FINAL}
        card, _ = Card.objects.get_or_create(timeframe=timeframe, period_start=start, defaults=defaults)

        updates = {}
        if card.period_end != end:
            updates["period_end"] = end
        if card.slug != slug:
            updates["slug"] = slug
        if updates:
            for key, value in updates.items():
                setattr(card, key, value)
            card.save(update_fields=list(updates.keys()))
        return card

    def _get_or_create_open_card_for_period(self, timeframe: str, start: datetime, end: datetime) -> Card:
        slug = self._card_slug(timeframe, start)
        defaults = {"period_end": end, "slug": slug, "status": Card.STATUS_OPEN}
        card, _ = Card.objects.get_or_create(timeframe=timeframe, period_start=start, defaults=defaults)

        updates = {}
        if card.period_end != end:
            updates["period_end"] = end
        if card.slug != slug:
            updates["slug"] = slug
        if card.status != Card.STATUS_FINAL and card.status != Card.STATUS_OPEN:
            updates["status"] = Card.STATUS_OPEN
        if updates:
            for key, value in updates.items():
                setattr(card, key, value)
            card.save(update_fields=list(updates.keys()))
        return card

    def _card_slug(self, timeframe: str, start: datetime) -> str:
        if timeframe == Card.TIMEFRAME_HOUR:
            return start.strftime("hour-%Y-%m-%d-%H")
        if timeframe == Card.TIMEFRAME_DAY:
            return start.strftime("day24-%Y-%m-%d-%H")
        if timeframe == Card.TIMEFRAME_WEEK:
            return start.strftime("week-%Y-%W")
        if timeframe == Card.TIMEFRAME_MONTH:
            return start.strftime("month-%Y-%m")
        return start.strftime("%Y-%m-%d")

    def _upsert_card_articles(
        self,
        *,
        card: Card,
        main_payload: dict,
        side_payloads: list[dict],
    ) -> None:
        main_title = main_payload.get("title") or "Financial Market Impact Update"
        main_slug = build_article_slug(
            title=main_title,
            period_start=card.period_start,
            article_uuid=card.uuid,
            kind=CardArticle.KIND_MAIN,
        )

        main_article, _ = CardArticle.objects.update_or_create(
            card=card,
            kind=CardArticle.KIND_MAIN,
            defaults={
                "uuid": card.uuid,
                "slug": main_slug,
                "title": main_title,
                "summary": main_payload.get("summary") or "",
                "body": main_payload.get("body") or "",
                "references": self._normalize_references(main_payload.get("references")),
                "impacts": main_payload.get("impacts") or [],
                "time_window": card.timeframe,
                "published_at": card.published_at,
            },
        )

        # keep payload slug aligned with persisted article slug
        main_payload["slug"] = main_article.slug

        if not card.articles.filter(kind=CardArticle.KIND_SIDE).exists():
            for payload in side_payloads:
                article_uuid = uuid4()
                side_title = payload.get("title") or "Market Detail"
                CardArticle.objects.create(
                    uuid=article_uuid,
                    slug=build_article_slug(
                        title=side_title,
                        period_start=card.period_start,
                        article_uuid=article_uuid,
                        kind=CardArticle.KIND_SIDE,
                    ),
                    card=card,
                    kind=CardArticle.KIND_SIDE,
                    title=side_title,
                    summary=payload.get("summary", ""),
                    body=payload.get("body", ""),
                    references=self._normalize_references(payload.get("references")),
                    impacts=[],
                    time_window=card.timeframe,
                    published_at=payload.get("published_at"),
                )

    def _ensure_card_assets(self, card: Card) -> None:
        enabled_symbol_labels = self._enabled_price_source_symbol_labels()
        existing_assets = list(card.assets.select_related("series").all())

        if not enabled_symbol_labels:
            if existing_assets:
                card.assets.all().delete()
            return

        enabled_symbols = set(enabled_symbol_labels.keys())
        stale_asset_ids = [asset.id for asset in existing_assets if asset.series.symbol not in enabled_symbols]
        if stale_asset_ids:
            CardAsset.objects.filter(id__in=stale_asset_ids).delete()

        existing_by_symbol = {asset.series.symbol: asset for asset in existing_assets if asset.series.symbol in enabled_symbols}
        series_by_symbol = {
            series.symbol: series
            for series in AssetSeries.objects.filter(symbol__in=list(enabled_symbols)).order_by("symbol")
        }

        for symbol, configured_label in enabled_symbol_labels.items():
            series = series_by_symbol.get(symbol)
            if not series:
                continue
            label = configured_label or series.label or symbol
            existing_asset = existing_by_symbol.get(symbol)
            if existing_asset is None:
                CardAsset.objects.create(card=card, series=series, label=label)
                continue
            if (existing_asset.label or "") != label:
                existing_asset.label = label
                existing_asset.save(update_fields=["label"])

    def _enabled_price_source_symbol_labels(self) -> dict[str, str]:
        rows = (
            PriceSource.objects.filter(enabled=True)
            .exclude(symbol__exact="")
            .order_by("symbol", "name", "id")
            .values("symbol", "chart_label", "name")
        )
        symbol_labels: dict[str, str] = {}
        explicit_labels: dict[str, bool] = {}
        for row in rows:
            symbol = (row.get("symbol") or "").strip()
            if not symbol:
                continue
            chart_label = (row.get("chart_label") or "").strip()
            explicit = bool(chart_label)
            label = chart_label or (row.get("name") or "").strip() or symbol
            if symbol not in symbol_labels:
                symbol_labels[symbol] = label
                explicit_labels[symbol] = explicit
                continue
            if explicit and not explicit_labels.get(symbol, False):
                symbol_labels[symbol] = label
                explicit_labels[symbol] = True
        return symbol_labels

    def _normalize_references(self, references: object) -> list[str]:
        if not references:
            return []
        urls: list[str] = []
        if isinstance(references, str):
            urls.extend(re.findall(r"https?://\S+", references))
        elif isinstance(references, (list, tuple)):
            for item in references:
                if isinstance(item, str):
                    urls.extend(re.findall(r"https?://\S+", item))
        cleaned = []
        for url in urls:
            trimmed = url.strip().rstrip(").,;")
            if trimmed and trimmed not in cleaned:
                cleaned.append(trimmed)
        return cleaned[:10]

    def _build_article_prompt(
        self,
        context: str,
        timeframe: str,
        period_start: datetime,
        period_end: datetime,
    ) -> str:
        template = self.config.article_prompt_template or "{context}"
        guardrails = (
            "You are an institutional financial journalist. "
            "Write as a human market reporter, not as a template or machine-generated bulletin. "
            "Write in clear, professional English and keep explanations straightforward. "
            "Include only events with direct or indirect impact on financial markets. "
            "Reject sports, entertainment, celebrity, lifestyle, and unrelated local stories. "
            "Do NOT write explicit timestamps or phrases like 'in this time window' in the article body. "
            "Return plain text only; do not output HTML tags, markdown formatting, social embeds, or XML fragments. "
            "Focus on what happened, why it matters, and likely market implications. "
            "Return JSON with keys: title, summary, article_text, impacts, importance_score, importance_reason, references."
        )
        body = template.replace("{context}", context)
        return f"{guardrails}\n\nSource records:\n{body}"

    def _fetch_api_source(self, source: NewsSource, *, client: Optional[httpx.Client] = None) -> list[dict]:
        if (source.api_key_param or source.api_key_header) and not source.api_key:
            raise RuntimeError("missing_api_key")
        params = {}
        headers = {}
        if source.api_key_header and source.api_key:
            headers[source.api_key_header] = source.api_key
        if source.api_key_param and source.api_key:
            params[source.api_key_param] = source.api_key
        if source.query_param and source.query:
            params[source.query_param] = source.query
        if source.language_param and source.language:
            params[source.language_param] = source.language
        if source.region_param and source.region:
            params[source.region_param] = source.region
        if source.topic_param and source.topic:
            params[source.topic_param] = source.topic
        if source.since_param and source.last_fetched_at:
            params[source.since_param] = self._format_since(source.last_fetched_at, source.since_format)

        http_client = client or self.client
        resp = http_client.get(source.base_url, params=params, headers=headers)
        if resp.status_code == 429:
            raise RuntimeError("rate_limited")
        if resp.status_code >= 400:
            raise RuntimeError(f"http_{resp.status_code}")

        data = resp.json()
        items = self._parse_api_items(data)
        items = self._filter_items_since(items, source.last_fetched_at)
        return items[: int(self.config.max_items_per_source)]

    def _fetch_rss_source(self, source: NewsSource, *, client: Optional[httpx.Client] = None) -> list[dict]:
        http_client = client or self.client
        resp = http_client.get(source.base_url)
        if resp.status_code == 429:
            raise RuntimeError("rate_limited")
        if resp.status_code >= 400:
            raise RuntimeError(f"http_{resp.status_code}")
        items = self._parse_rss_items(resp.text)
        items = self._filter_items_since(items, source.last_fetched_at)
        return items[: int(self.config.max_items_per_source)]

    def _parse_api_items(self, data: object) -> list[dict]:
        candidates = self._extract_api_candidates(data)
        if not candidates:
            return []
        items = []
        for entry in candidates:
            if isinstance(entry, dict):
                normalized = self._normalize_item(entry)
                if normalized.get("title") or normalized.get("summary") or normalized.get("content"):
                    items.append(normalized)
        return items

    def _extract_api_candidates(self, data: object) -> list[dict]:
        if isinstance(data, list):
            return [item for item in data if isinstance(item, dict)]

        if not isinstance(data, dict):
            return []

        candidates: list[dict] = []
        list_keys = (
            "articles",
            "data",
            "results",
            "news",
            "feed",
            "items",
            "stories",
            "entries",
            "releases",
        )
        for key in list_keys:
            value = data.get(key)
            if isinstance(value, list):
                candidates.extend(item for item in value if isinstance(item, dict))
            elif isinstance(value, dict):
                nested = (
                    value.get("items")
                    or value.get("results")
                    or value.get("articles")
                    or value.get("news")
                    or value.get("feed")
                )
                if isinstance(nested, list):
                    candidates.extend(item for item in nested if isinstance(item, dict))

        if not candidates and any(
            key in data for key in ("title", "headline", "summary", "description", "content", "url", "link")
        ):
            candidates.append(data)

        return candidates

    def _parse_rss_items(self, xml_text: str) -> list[dict]:
        try:
            root = ET.fromstring(xml_text)
        except Exception:
            return []
        items = []

        for item in root.findall(".//item"):
            title = (item.findtext("title") or "").strip()
            description = (item.findtext("description") or "").strip()
            content_encoded = ""
            for child in list(item):
                if isinstance(child.tag, str) and child.tag.endswith("encoded"):
                    content_encoded = (child.text or "").strip()
                    break
            link = (item.findtext("link") or "").strip()
            pub_date = (item.findtext("pubDate") or "").strip()
            items.append(
                {
                    "title": title,
                    "summary": description,
                    "content": content_encoded or description or title,
                    "url": link,
                    "published_at": self._parse_datetime(pub_date),
                }
            )

        for entry in root.findall(".//{http://www.w3.org/2005/Atom}entry") + root.findall(".//entry"):
            title = (
                entry.findtext("{http://www.w3.org/2005/Atom}title")
                or entry.findtext("title")
                or ""
            ).strip()
            summary = (
                entry.findtext("{http://www.w3.org/2005/Atom}summary")
                or entry.findtext("summary")
                or ""
            ).strip()
            content = (
                entry.findtext("{http://www.w3.org/2005/Atom}content")
                or entry.findtext("content")
                or summary
                or title
            ).strip()
            link = self._extract_atom_link(entry)
            published = (
                entry.findtext("{http://www.w3.org/2005/Atom}updated")
                or entry.findtext("{http://www.w3.org/2005/Atom}published")
                or entry.findtext("updated")
                or entry.findtext("published")
                or ""
            ).strip()
            items.append(
                {
                    "title": title,
                    "summary": summary,
                    "content": content,
                    "url": link,
                    "published_at": self._parse_datetime(published),
                }
            )
        return items

    def _normalize_item(self, entry: dict) -> dict:
        title = self._first_text(entry, ("title", "headline", "name", "event", "subject"))
        summary = self._first_text(entry, ("summary", "description", "abstract", "teaser", "text"))
        content = self._first_text(entry, ("content", "body", "details", "snippet", "full_text")) or summary or title
        url = self._extract_entry_url(entry)
        published = (
            entry.get("published_at")
            or entry.get("publishedAt")
            or entry.get("pubDate")
            or entry.get("date")
            or entry.get("datetime")
            or entry.get("time_published")
            or entry.get("updated")
            or entry.get("published")
        )
        return {
            "title": title,
            "summary": summary,
            "content": content,
            "url": url,
            "published_at": self._parse_provider_datetime(published),
        }

    @staticmethod
    def _first_text(entry: dict, keys: tuple[str, ...]) -> str:
        for key in keys:
            value = entry.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        return ""

    @staticmethod
    def _extract_entry_url(entry: dict) -> str:
        url = entry.get("url") or entry.get("link") or entry.get("uri") or entry.get("id") or ""
        if isinstance(url, str) and url.strip():
            return url.strip()

        links = entry.get("links")
        if isinstance(links, list):
            for item in links:
                if isinstance(item, dict):
                    href = item.get("href") or item.get("url") or item.get("link")
                    if isinstance(href, str) and href.strip():
                        return href.strip()
        return ""

    @staticmethod
    def _extract_atom_link(entry) -> str:
        # Atom links are often in attributes rather than text.
        for child in list(entry):
            if not isinstance(child.tag, str):
                continue
            if child.tag.endswith("link"):
                href = (child.attrib.get("href") or "").strip()
                if href:
                    return href
                text = (child.text or "").strip()
                if text:
                    return text
        return (entry.findtext("link") or "").strip()

    def _parse_provider_datetime(self, value: object) -> Optional[datetime]:
        if value is None or value == "":
            return None

        if isinstance(value, (int, float)):
            ts = float(value)
            if ts > 1e12:
                ts = ts / 1000.0
            try:
                return datetime.fromtimestamp(ts, tz=timezone.utc)
            except Exception:
                return None

        text = str(value).strip()
        if not text:
            return None

        if re.fullmatch(r"\d{8}T\d{6}", text):
            try:
                return datetime.strptime(text, "%Y%m%dT%H%M%S").replace(tzinfo=timezone.utc)
            except ValueError:
                return None

        return self._parse_datetime(text)

    def _filter_items_since(self, items: list[dict], last_fetched_at: Optional[datetime]) -> list[dict]:
        if not last_fetched_at:
            return items
        filtered = []
        for item in items:
            published_at = item.get("published_at")
            if published_at is None or published_at >= last_fetched_at:
                filtered.append(item)
        return filtered

    def _format_since(self, value: datetime, fmt: str) -> str:
        if fmt == "unix":
            return str(int(value.timestamp()))
        if fmt == "rfc3339":
            return value.isoformat()
        return value.isoformat()

    def _apply_backoff(self, source: NewsSource, reason: str) -> None:
        delay = max(60, int(source.rate_limit_seconds or 0))
        source.backoff_until = _utc_now() + timedelta(seconds=delay)
        self._record_source_error(source, reason)

    def _record_source_error(self, source: NewsSource, error: str) -> None:
        source.failure_count += 1
        source.last_error = error[:2000]
        source.save(update_fields=["failure_count", "last_error", "backoff_until"])

    def _clean_text(self, text: str) -> str:
        if not text:
            return ""
        soup = BeautifulSoup(text, "html.parser")
        for tag in soup(["script", "style", "noscript"]):
            tag.decompose()
        raw = soup.get_text(" ")
        raw = re.sub(r"\s+", " ", raw).strip()
        return raw

    def _store_raw_item(self, source: NewsSource, item: dict, cleaned_text: str) -> None:
        published = self._parse_datetime(item.get("published_at"))
        if not published:
            return

        url = (item.get("url") or "").strip()
        if not url:
            url = self._synthetic_url(source, item, published)

        safe_item = self._safe_json(item)
        title = (item.get("title") or "").strip()
        summary = (item.get("summary") or "").strip()
        content = (item.get("content") or "").strip()

        RawNewsItem.objects.update_or_create(
            url=url,
            defaults={
                "source_name": source.name,
                "source_url": source.base_url,
                "title": title,
                "summary": summary,
                "content": content,
                "cleaned_text": cleaned_text,
                "published_at": published,
                "fetched_at": _utc_now(),
                "raw_payload": safe_item,
            },
        )

    def _synthetic_url(self, source: NewsSource, item: dict, published: datetime) -> str:
        title = (item.get("title") or item.get("summary") or item.get("content") or "untitled")[:200]
        digest = hashlib.sha1(f"{source.base_url}|{title}|{published.isoformat()}".encode("utf-8")).hexdigest()[:20]
        source_slug = slugify(source.name or "source") or "source"
        return f"https://synthetic.local/{source_slug}/{published.strftime('%Y%m%d%H%M%S')}-{digest}"

    def _dedupe_key(self, item: dict, title: str, published_at: datetime) -> str:
        url = (item.get("url") or "").strip()
        if url:
            return url
        seed = f"{title}|{published_at.isoformat()}"
        return hashlib.sha1(seed.encode("utf-8")).hexdigest()

    def _log_event(
        self,
        *,
        run: Optional[AgentRun],
        step: str,
        message: str,
        content: str = "",
        metadata: Optional[dict] = None,
        level: str = AgentLogEvent.LEVEL_INFO,
        seed_url: str = "",
        url: str = "",
    ) -> None:
        clipped_content, clip_meta = self._clip_log(content)
        meta = self._safe_json(dict(metadata or {}))
        if clip_meta:
            meta.update(clip_meta)
        AgentLogEvent.objects.create(
            run=run,
            seed_url=seed_url or "",
            url=url or "",
            step=step,
            level=level,
            message=message[:255],
            content=clipped_content,
            metadata=meta,
        )

    def _clip_log(self, text: str) -> tuple[str, dict]:
        if not text:
            return "", {}
        max_chars = max(0, int(self.log_max_chars))
        if max_chars <= 0 or len(text) <= max_chars:
            return text, {}
        head = int(max_chars * 0.7)
        tail = max_chars - head
        clipped = text[:head] + "\n...\n" + text[-tail:]
        return clipped, {"clipped": True, "original_chars": len(text), "stored_chars": len(clipped)}

    def _llm_budget_remaining(self) -> int:
        return max(0, int(self.llm_request_budget) - int(self.llm_requests_used))

    def _consume_llm_budget(
        self,
        *,
        run: Optional[AgentRun],
        purpose: str,
        reserve: int = 0,
    ) -> bool:
        remaining = self._llm_budget_remaining()
        required_remaining = max(0, int(reserve))
        if remaining <= required_remaining:
            if not self._llm_budget_exhausted_logged:
                self._log_event(
                    run=run,
                    step=AgentLogEvent.STEP_NEXT_STEP,
                    level=AgentLogEvent.LEVEL_WARN,
                    message="llm_budget_exhausted",
                    metadata={
                        "purpose": purpose,
                        "llm_requests_used": self.llm_requests_used,
                        "llm_request_budget": self.llm_request_budget,
                        "llm_reserved_for_articles": required_remaining,
                    },
                )
                self._llm_budget_exhausted_logged = True
            return False
        self.llm_requests_used += 1
        return True

    def _budgeted_generate_json(
        self,
        prompt: str,
        *,
        run: Optional[AgentRun],
        purpose: str,
        reserve: int = 0,
    ) -> Optional[dict]:
        if not self._consume_llm_budget(run=run, purpose=purpose, reserve=reserve):
            return None
        return self.llm.generate_json(prompt)

    def _should_apply_llm_filter(self, run: Optional[AgentRun], heuristic_score: int) -> bool:
        if run is None or not bool(getattr(run, "use_llm_filtering", False)):
            return False
        if not self.llm.enabled:
            return False
        if not (self.config.filter_prompt_template or "").strip():
            return False
        if self._llm_budget_remaining() <= self.llm_reserved_for_articles:
            return False
        return heuristic_score >= (self._MIN_RELEVANCE_SCORE - self._LLM_FILTER_SCORE_BUFFER)

    def _llm_filter_decision(
        self,
        *,
        title: str,
        summary: str,
        content: str,
        heuristic_score: int,
        run: Optional[AgentRun],
        source_name: str,
        source_url: str,
        item_url: str,
    ) -> Optional[dict]:
        template = (self.config.filter_prompt_template or "").strip()
        if not template:
            return None

        prompt = (
            template.replace("{title}", self._compact_text(title, 260))
            .replace("{summary}", self._compact_text(summary, 380))
            .replace("{content}", self._compact_text(content, self._LLM_FILTER_CONTEXT_CHARS))
            .replace("{heuristic_score}", str(int(heuristic_score)))
        )
        output = self._budgeted_generate_json(
            prompt,
            run=run,
            purpose="filter_decision",
            reserve=self.llm_reserved_for_articles,
        )
        if not isinstance(output, dict):
            return None

        decision = str(output.get("decision") or "").strip().lower()
        accepted_values = {"accept", "accepted", "include", "relevant", "yes", "allow"}
        rejected_values = {"reject", "rejected", "exclude", "irrelevant", "no", "drop"}
        if decision in accepted_values:
            accepted = True
        elif decision in rejected_values:
            accepted = False
        else:
            return None

        importance_score = self._normalize_importance_score(output.get("importance_score")) or 1
        reason = self._compact_text(str(output.get("reason") or ""), 220)
        confidence_raw = output.get("confidence")
        try:
            confidence = float(confidence_raw)
        except (TypeError, ValueError):
            confidence = 0.0
        confidence = max(0.0, min(1.0, confidence))

        if not accepted:
            self._log_event(
                run=run,
                step=AgentLogEvent.STEP_NEXT_STEP,
                message="llm_filter_rejected_item",
                metadata={
                    "source": source_name,
                    "source_url": source_url,
                    "url": item_url,
                    "heuristic_score": heuristic_score,
                    "importance_score": importance_score,
                    "confidence": confidence,
                    "reason": reason,
                },
            )

        return {
            "accepted": accepted,
            "importance_score": importance_score,
            "confidence": confidence,
            "reason": reason,
        }

    @staticmethod
    def _normalize_importance_score(value: object) -> Optional[int]:
        if value is None:
            return None
        if isinstance(value, str):
            text = value.strip().lower()
            if not text:
                return None
            alias_map = {
                "low": 1,
                "minor": 1,
                "localized": 1,
                "medium": 2,
                "moderate": 2,
                "regional": 2,
                "high": 3,
                "severe": 3,
                "global": 3,
                "systemic": 3,
            }
            if text in alias_map:
                return alias_map[text]
            try:
                value = int(float(text))
            except (TypeError, ValueError):
                return None

        if isinstance(value, (int, float)):
            score = int(round(float(value)))
            return max(1, min(3, score))
        return None

    def _infer_importance_from_records(
        self,
        records: list[dict],
        *,
        title: str,
        summary: str,
        body: str,
    ) -> tuple[int, str]:
        combined = " ".join(
            [
                title or "",
                summary or "",
                body or "",
                *[
                    f"{item.get('title') or ''} {item.get('summary') or ''} {item.get('content') or ''}"
                    for item in (records or [])
                ],
            ]
        ).lower()

        high_impact_tokens = [
            "central bank",
            "interest rate",
            "rate hike",
            "rate cut",
            "inflation",
            "cpi",
            "gdp",
            "recession",
            "banking crisis",
            "default",
            "sanction",
            "tariff",
            "war",
            "oil shock",
            "energy disruption",
            "sovereign debt",
        ]
        medium_impact_tokens = [
            "earnings",
            "guidance",
            "merger",
            "acquisition",
            "treasury",
            "yield",
            "credit spread",
            "commodity",
            "supply chain",
            "regulation",
            "antitrust",
            "pmi",
            "jobs report",
            "unemployment",
            "housing",
        ]

        if any(token in combined for token in high_impact_tokens):
            score = 3
        elif any(token in combined for token in medium_impact_tokens):
            score = 2
        else:
            score = 1

        if len(records or []) >= 10 and score < 3:
            score += 1

        channels = []
        if any(token in combined for token in ["rate", "yield", "bond", "treasury", "inflation", "central bank"]):
            channels.append("rates and monetary policy")
        if any(token in combined for token in ["currency", "forex", "fx", "dollar", "euro", "yen"]):
            channels.append("FX positioning")
        if any(token in combined for token in ["oil", "gas", "commodity", "energy", "metal"]):
            channels.append("commodity pricing")
        if any(token in combined for token in ["equity", "stock", "earnings", "valuation", "sector"]):
            channels.append("equity risk appetite")
        if any(token in combined for token in ["credit", "default", "spread", "bank"]):
            channels.append("credit conditions")
        if not channels:
            channels.append("broad macro sentiment")

        scope = {1: "localized", 2: "regional or sector-wide", 3: "global cross-asset"}[score]
        reason = f"{scope.capitalize()} market impact expected via {channels[0]}."
        if score >= 2 and len(channels) > 1:
            reason = f"{scope.capitalize()} market impact expected via {channels[0]} and {channels[1]}."
        return score, self._compact_text(reason, 280)

    @staticmethod
    def _parse_datetime(value: object) -> Optional[datetime]:
        if not value:
            return None
        try:
            dt = dtparser.parse(str(value))
        except Exception:
            return None
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt

    @staticmethod
    def _is_financially_relevant(text: str, title: str = "") -> bool:
        return AgentService._relevance_score(text, title) >= AgentService._MIN_RELEVANCE_SCORE

    @staticmethod
    def _relevance_score(text: str, title: str = "") -> int:
        combined = (text + " " + title).lower()

        financial_keywords = [
            "fed",
            "central bank",
            "ecb",
            "bank of england",
            "pboc",
            "boj",
            "interest rate",
            "rate hike",
            "rate cut",
            "monetary policy",
            "qe",
            "quantitative easing",
            "inflation",
            "cpi",
            "ppi",
            "gdp",
            "recession",
            "unemployment",
            "jobs report",
            "stock market",
            "equity",
            "nasdaq",
            "s&p",
            "dow jones",
            "bond",
            "yield",
            "treasury",
            "dollar",
            "euro",
            "currency",
            "forex",
            "fx",
            "commodity",
            "oil",
            "gas",
            "gold",
            "earnings",
            "revenue",
            "profit",
            "eps",
            "guidance",
            "m&a",
            "merger",
            "acquisition",
            "ipo",
            "bankruptcy",
            "default",
            "tariff",
            "trade",
            "supply chain",
            "logistics",
            "regulation",
            "sec",
            "antitrust",
            "credit rating",
            "moody",
            "fitch",
            "sanction",
            "geopolitical",
            "energy",
            "oil price",
            "natural gas",
            "commodity shock",
            "yield curve",
            "credit spread",
            "mortgage",
            "housing",
            "pmi",
            "manufacturing",
            "volatility",
            "vix",
            "liquidity",
            "leverage",
            "derivative",
            "hedge",
            "bank",
        ]

        reject_keywords = [
            "celebrity",
            "actor",
            "actress",
            "sports",
            "football",
            "basketball",
            "soccer",
            "award",
            "oscar",
            "emmy",
            "grammy",
            "concert",
            "album",
            "band",
            "wedding",
            "divorce",
            "relationship",
            "celebrity gossip",
            "influencer",
            "tiktok",
            "instagram",
            "movie",
            "film",
            "netflix",
            "fashion",
            "beauty",
            "restaurant",
            "travel",
            "vacation",
            "hotel",
            "resort",
            "pet",
            "dog",
            "cat",
            "game",
            "esports",
        ]

        score = 0

        for kw in financial_keywords:
            if kw in combined:
                score += 2

        title_lower = (title or "").lower()
        for high in ["central bank", "fed", "interest rate", "inflation", "gdp", "default", "bankruptcy", "sanction"]:
            if high in title_lower:
                score += 4

        for kw in reject_keywords:
            if kw in combined:
                score -= 3

        relevant_sentences = AgentService._extract_relevant_sentences(text)
        if relevant_sentences:
            score += 3

        if len(combined) < 200 and score > 0:
            score += 1

        return score

    @staticmethod
    def _extract_relevant_sentences(text: str) -> str:
        if not text:
            return ""
        sentences = re.split(r"(?<=[\.\?!])\s+", text)
        financial_terms = [
            "fed",
            "central bank",
            "interest rate",
            "inflation",
            "gdp",
            "unemployment",
            "earnings",
            "revenue",
            "m&a",
            "merger",
            "acquisition",
            "ipo",
            "bankruptcy",
            "bond",
            "yield",
            "treasury",
            "currency",
            "forex",
            "oil",
            "gas",
            "commodity",
            "tariff",
            "trade",
            "sanction",
            "credit",
            "rating",
            "regulation",
            "sec",
        ]
        picks = []
        for sentence in sentences:
            low = sentence.lower()
            if any(term in low for term in financial_terms):
                picks.append(sentence.strip())
        return " ".join(picks).strip()

    @classmethod
    def _safe_json(cls, value: object):
        return _safe_json_value(value)


RUN_LOCK = threading.Lock()
RUN_THREAD: Optional[threading.Thread] = None
RUN_ACTIVE = False
RUN_LAST_ERROR = ""
RUN_LAST_STARTED_AT: Optional[datetime] = None
RUN_LAST_FINISHED_AT: Optional[datetime] = None

RUN_FOREVER_THREAD: Optional[threading.Thread] = None
RUN_FOREVER_ACTIVE = False
RUN_FOREVER_STATE = "idle"
RUN_FOREVER_LAST_ERROR = ""
RUN_FOREVER_STARTED_AT: Optional[datetime] = None
RUN_FOREVER_LAST_HEARTBEAT_AT: Optional[datetime] = None
RUN_FOREVER_LAST_NEWS_AT: Optional[datetime] = None
RUN_FOREVER_LAST_PRICE_AT: Optional[datetime] = None
RUN_FOREVER_ITERATIONS = 0
RUN_FOREVER_PAUSED = False
RUN_FOREVER_STOP_REQUESTED = False
RUN_FOREVER_CURRENT_ACTION = "idle"


def _log_loop_event(message: str, *, level: str = AgentLogEvent.LEVEL_INFO, metadata: Optional[dict] = None) -> None:
    AgentLogEvent.objects.create(
        run=None,
        step=AgentLogEvent.STEP_LOOP_STATE,
        level=level,
        message=message[:255],
        content="",
        metadata=_safe_json_value(metadata or {}),
    )


def start_agent_async(run_id: Optional[int] = None) -> bool:
    global RUN_THREAD, RUN_ACTIVE, RUN_LAST_ERROR, RUN_LAST_STARTED_AT, RUN_LAST_FINISHED_AT
    with RUN_LOCK:
        if RUN_THREAD and RUN_THREAD.is_alive():
            return False

        RUN_ACTIVE = True
        RUN_LAST_ERROR = ""
        RUN_LAST_STARTED_AT = _utc_now()
        RUN_LAST_FINISHED_AT = None

        def _runner() -> None:
            global RUN_ACTIVE, RUN_LAST_ERROR, RUN_LAST_FINISHED_AT
            try:
                service = AgentService()
                run = AgentRun.objects.filter(pk=run_id).first() if run_id is not None else None
                service.run(run)
            except Exception as exc:
                RUN_LAST_ERROR = str(exc)[:2000]
            finally:
                RUN_ACTIVE = False
                RUN_LAST_FINISHED_AT = _utc_now()

        RUN_THREAD = threading.Thread(target=_runner, name="agent-runner", daemon=True)
        RUN_THREAD.start()
        return True


def start_run_forever_async() -> bool:
    global RUN_FOREVER_THREAD
    global RUN_FOREVER_ACTIVE
    global RUN_FOREVER_STATE
    global RUN_FOREVER_LAST_ERROR
    global RUN_FOREVER_STARTED_AT
    global RUN_FOREVER_LAST_HEARTBEAT_AT
    global RUN_FOREVER_LAST_NEWS_AT
    global RUN_FOREVER_LAST_PRICE_AT
    global RUN_FOREVER_ITERATIONS
    global RUN_FOREVER_PAUSED
    global RUN_FOREVER_STOP_REQUESTED
    global RUN_FOREVER_CURRENT_ACTION

    with RUN_LOCK:
        if RUN_FOREVER_THREAD and RUN_FOREVER_THREAD.is_alive():
            return False

        config = get_config()
        if not config.run_forever_enabled:
            config.run_forever_enabled = True
            config.save(update_fields=["run_forever_enabled"])

        RUN_FOREVER_ACTIVE = True
        RUN_FOREVER_STATE = "running"
        RUN_FOREVER_LAST_ERROR = ""
        RUN_FOREVER_STARTED_AT = _utc_now()
        RUN_FOREVER_LAST_HEARTBEAT_AT = RUN_FOREVER_STARTED_AT
        RUN_FOREVER_LAST_NEWS_AT = None
        RUN_FOREVER_LAST_PRICE_AT = None
        RUN_FOREVER_ITERATIONS = 0
        RUN_FOREVER_PAUSED = False
        RUN_FOREVER_STOP_REQUESTED = False
        RUN_FOREVER_CURRENT_ACTION = "starting"

    _log_loop_event("run_forever_started", metadata={"started_at": RUN_FOREVER_STARTED_AT})

    def _runner() -> None:
        global RUN_FOREVER_ACTIVE
        global RUN_FOREVER_STATE
        global RUN_FOREVER_LAST_ERROR
        global RUN_FOREVER_LAST_HEARTBEAT_AT
        global RUN_FOREVER_LAST_NEWS_AT
        global RUN_FOREVER_LAST_PRICE_AT
        global RUN_FOREVER_ITERATIONS
        global RUN_FOREVER_PAUSED
        global RUN_FOREVER_STOP_REQUESTED
        global RUN_FOREVER_CURRENT_ACTION

        last_news_at_monotonic = 0.0
        last_price_at_monotonic = 0.0

        try:
            while True:
                with RUN_LOCK:
                    stop_requested = RUN_FOREVER_STOP_REQUESTED
                    paused = RUN_FOREVER_PAUSED
                    RUN_FOREVER_LAST_HEARTBEAT_AT = _utc_now()

                if stop_requested:
                    with RUN_LOCK:
                        RUN_FOREVER_STATE = "stopping"
                        RUN_FOREVER_CURRENT_ACTION = "stopping"
                    break

                if paused:
                    with RUN_LOCK:
                        RUN_FOREVER_STATE = "paused"
                        RUN_FOREVER_CURRENT_ACTION = "paused"
                    time.sleep(1.0)
                    continue

                config = get_config()
                if not config.run_forever_enabled:
                    with RUN_LOCK:
                        RUN_FOREVER_STATE = "paused"
                        RUN_FOREVER_CURRENT_ACTION = "disabled_in_config"
                    time.sleep(1.0)
                    continue

                now_monotonic = time.monotonic()
                news_interval = max(60.0, float(config.loop_interval_minutes or 1.0) * 60.0)
                price_interval = max(5.0, float(config.price_loop_interval_seconds or 60.0))

                with RUN_LOCK:
                    RUN_FOREVER_STATE = "running"

                if now_monotonic - last_news_at_monotonic >= news_interval:
                    with RUN_LOCK:
                        RUN_FOREVER_CURRENT_ACTION = "news_run"
                    try:
                        service = AgentService(config=config)
                        service.run()
                        with RUN_LOCK:
                            RUN_FOREVER_LAST_NEWS_AT = _utc_now()
                            RUN_FOREVER_ITERATIONS += 1
                    except Exception as exc:
                        RUN_FOREVER_LAST_ERROR = str(exc)[:2000]
                        _log_loop_event(
                            "run_forever_news_run_failed",
                            level=AgentLogEvent.LEVEL_WARN,
                            metadata={"error": RUN_FOREVER_LAST_ERROR},
                        )
                    finally:
                        last_news_at_monotonic = time.monotonic()

                if now_monotonic - last_price_at_monotonic >= price_interval:
                    with RUN_LOCK:
                        RUN_FOREVER_CURRENT_ACTION = "price_sync"
                    try:
                        sync_price_feeds(user_agent=config.user_agent)
                        with RUN_LOCK:
                            RUN_FOREVER_LAST_PRICE_AT = _utc_now()
                    except Exception as exc:
                        RUN_FOREVER_LAST_ERROR = str(exc)[:2000]
                        _log_loop_event(
                            "run_forever_price_sync_failed",
                            level=AgentLogEvent.LEVEL_WARN,
                            metadata={"error": RUN_FOREVER_LAST_ERROR},
                        )
                    finally:
                        last_price_at_monotonic = time.monotonic()

                with RUN_LOCK:
                    if RUN_FOREVER_STATE == "running":
                        RUN_FOREVER_CURRENT_ACTION = "sleeping"
                time.sleep(1.0)
        finally:
            with RUN_LOCK:
                RUN_FOREVER_ACTIVE = False
                RUN_FOREVER_STATE = "idle"
                RUN_FOREVER_CURRENT_ACTION = "idle"
                RUN_FOREVER_STOP_REQUESTED = False
                RUN_FOREVER_PAUSED = False
            _log_loop_event("run_forever_stopped")

    with RUN_LOCK:
        RUN_FOREVER_THREAD = threading.Thread(target=_runner, name="run-forever", daemon=True)
        RUN_FOREVER_THREAD.start()
    return True


def pause_run_forever() -> bool:
    global RUN_FOREVER_PAUSED, RUN_FOREVER_STATE, RUN_FOREVER_CURRENT_ACTION
    with RUN_LOCK:
        if not RUN_FOREVER_THREAD or not RUN_FOREVER_THREAD.is_alive():
            return False
        RUN_FOREVER_PAUSED = True
        RUN_FOREVER_STATE = "paused"
        RUN_FOREVER_CURRENT_ACTION = "paused"
    _log_loop_event("run_forever_paused")
    return True


def resume_run_forever() -> bool:
    global RUN_FOREVER_PAUSED, RUN_FOREVER_STATE, RUN_FOREVER_CURRENT_ACTION
    with RUN_LOCK:
        if not RUN_FOREVER_THREAD or not RUN_FOREVER_THREAD.is_alive():
            return False
        RUN_FOREVER_PAUSED = False
        RUN_FOREVER_STATE = "running"
        RUN_FOREVER_CURRENT_ACTION = "resumed"
    _log_loop_event("run_forever_resumed")
    return True


def stop_run_forever() -> bool:
    global RUN_FOREVER_STOP_REQUESTED, RUN_FOREVER_PAUSED, RUN_FOREVER_STATE, RUN_FOREVER_CURRENT_ACTION

    with RUN_LOCK:
        if not RUN_FOREVER_THREAD or not RUN_FOREVER_THREAD.is_alive():
            return False
        RUN_FOREVER_STOP_REQUESTED = True
        RUN_FOREVER_PAUSED = False
        RUN_FOREVER_STATE = "stopping"
        RUN_FOREVER_CURRENT_ACTION = "stopping"

    config = get_config()
    if config.run_forever_enabled:
        config.run_forever_enabled = False
        config.save(update_fields=["run_forever_enabled"])

    _log_loop_event("run_forever_stop_requested")
    return True


def run_forever_status() -> dict:
    with RUN_LOCK:
        running = bool(RUN_FOREVER_ACTIVE and RUN_FOREVER_THREAD and RUN_FOREVER_THREAD.is_alive())
        return {
            "running": running,
            "state": RUN_FOREVER_STATE,
            "paused": bool(RUN_FOREVER_PAUSED),
            "stop_requested": bool(RUN_FOREVER_STOP_REQUESTED),
            "current_action": RUN_FOREVER_CURRENT_ACTION,
            "started_at": RUN_FOREVER_STARTED_AT,
            "last_heartbeat_at": RUN_FOREVER_LAST_HEARTBEAT_AT,
            "last_news_run_at": RUN_FOREVER_LAST_NEWS_AT,
            "last_price_sync_at": RUN_FOREVER_LAST_PRICE_AT,
            "iterations": RUN_FOREVER_ITERATIONS,
            "last_error": RUN_FOREVER_LAST_ERROR,
        }


def agent_live_status() -> dict:
    last_run = AgentRun.objects.first()
    return {
        "running": RUN_ACTIVE,
        "last_error": RUN_LAST_ERROR,
        "last_started_at": RUN_LAST_STARTED_AT,
        "last_finished_at": RUN_LAST_FINISHED_AT,
        "last_run": {
            "status": last_run.status,
            "started_at": last_run.started_at,
            "ended_at": last_run.ended_at,
            "pages_processed": last_run.pages_processed,
            "articles_created": last_run.articles_created,
            "queued_urls": last_run.queued_urls,
            "last_error": last_run.last_error,
        }
        if last_run
        else None,
    }
