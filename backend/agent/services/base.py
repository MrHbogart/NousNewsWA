from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional

import httpx
from django.conf import settings
from django.db.models import Sum

from agent.llm import LLMClient
from agent.models import AgentConfig, AgentLogEvent, AgentRun


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


class AgentServiceCore:
    """Shared state, construction, and the top-level run() orchestration.

    Combined with the other *Mixin classes in agent/services/service.py to form
    the full AgentService. Split out of one ~2700-line file for readability; the
    methods below still call into fetching/cards/content/scoring/budget methods
    via self, exactly as before the split.
    """

    _MIN_RELEVANCE_SCORE = int(getattr(settings, "AGENT_MIN_RELEVANCE_SCORE", 4))
    _MAX_HOURLY_BACKFILL_HOURS = int(getattr(settings, "AGENT_MAX_HOURLY_BACKFILL_HOURS", 72))
    _AFTERMATH_MAX_AGE_DAYS = int(getattr(settings, "AGENT_AFTERMATH_MAX_AGE_DAYS", 7))
    _MAX_AGGREGATE_BACKFILL_PERIODS = int(getattr(settings, "AGENT_MAX_AGGREGATE_BACKFILL_PERIODS", 16))
    _LLM_FILTER_SCORE_BUFFER = int(getattr(settings, "AGENT_LLM_FILTER_SCORE_BUFFER", 2))
    _LLM_FILTER_CONTEXT_CHARS = int(getattr(settings, "AGENT_LLM_FILTER_CONTEXT_CHARS", 1800))
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
        self.llm_request_budget = self._remaining_daily_llm_budget()
        self.llm_reserved_for_articles = int(self._LLM_RESERVED_FOR_ARTICLES)
        self.llm_requests_used = 0
        self._llm_budget_exhausted_logged = False
        self.economist_agent_enabled = bool(self._ENABLE_ECONOMIST_AGENT)

    def _remaining_daily_llm_budget(self) -> int:
        day_start = _utc_now().replace(hour=0, minute=0, second=0, microsecond=0)
        used_today = (
            AgentRun.objects.filter(started_at__gte=day_start).aggregate(total=Sum("llm_requests"))["total"] or 0
        )
        return max(0, int(self.config.llm_daily_request_budget) - int(used_today))

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
            # Permanent cards first so they get the LLM budget; the open
            # current-hour card is refreshed with whatever is left.
            hourly_created = self._finalize_due_hourly_cards(run, now)
            aggregate_created = self._finalize_due_aggregate_cards(run, now)
            aftermath_created = self._finalize_due_aftermath_cards(run, now)
            self._refresh_current_hour_card(run, now)
            stats.articles_created = hourly_created + aggregate_created + aftermath_created

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
                    "hourly_cards_finalized": hourly_created,
                    "aggregate_cards_finalized": aggregate_created,
                    "aftermath_cards_finalized": aftermath_created,
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
            run.llm_requests = self.llm_requests_used
            run.llm_prompt_tokens = self.llm.prompt_tokens
            run.llm_completion_tokens = self.llm.completion_tokens
            run.ended_at = _utc_now()
            run.save(
                update_fields=[
                    "status",
                    "last_error",
                    "pages_processed",
                    "articles_created",
                    "queued_urls",
                    "llm_requests",
                    "llm_prompt_tokens",
                    "llm_completion_tokens",
                    "ended_at",
                ]
            )
            self.close()
        return run
