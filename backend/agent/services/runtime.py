from __future__ import annotations

import threading
import time
from typing import Callable, Optional

from django.db import close_old_connections, connection
from django.utils import timezone

from agent.models import AgentConfig, AgentLogEvent, AgentRun, AgentWorker
from agent.price_sync import sync_price_feeds
from agent.retention import prune_old_data

from .base import _safe_json_value, get_config
from .service import AgentService

HEARTBEAT_STALE_SECONDS = 30
HEARTBEAT_EVERY_SECONDS = 10


def _log_loop_event(message: str, *, level: str = AgentLogEvent.LEVEL_INFO, metadata: Optional[dict] = None) -> None:
    AgentLogEvent.objects.create(
        run=None,
        step=AgentLogEvent.STEP_LOOP_STATE,
        level=level,
        message=message[:255],
        content="",
        metadata=_safe_json_value(metadata or {}),
    )


def _worker_row() -> AgentWorker:
    worker, _ = AgentWorker.objects.get_or_create(pk=1)
    return worker


# ---- control side (web process): only writes flags, never runs work ----


def _set_config(message: str, **fields) -> dict:
    config = get_config()
    AgentConfig.objects.filter(pk=config.pk).update(**fields)
    _log_loop_event(message)
    return worker_status()


def request_start() -> dict:
    return _set_config("run_forever_start_requested", run_forever_enabled=True, run_forever_paused=False)


def request_stop() -> dict:
    return _set_config("run_forever_stop_requested", run_forever_enabled=False, run_forever_paused=False)


def request_pause() -> dict:
    return _set_config("run_forever_pause_requested", run_forever_paused=True)


def request_resume() -> dict:
    return _set_config("run_forever_resume_requested", run_forever_paused=False)


def request_run_once() -> dict:
    return _set_config("run_once_requested", run_once_requested=True)


def worker_status() -> dict:
    config = get_config()
    worker = _worker_row()
    online = bool(
        worker.heartbeat_at
        and (timezone.now() - worker.heartbeat_at).total_seconds() < HEARTBEAT_STALE_SECONDS
    )
    if not online:
        state = "offline"
    elif not config.run_forever_enabled:
        state = "idle"
    elif config.run_forever_paused:
        state = "paused"
    else:
        state = "running"
    return {
        "running": online and config.run_forever_enabled,
        "worker_online": online,
        "enabled": config.run_forever_enabled,
        "state": state,
        "paused": config.run_forever_paused,
        "run_once_requested": config.run_once_requested,
        "current_action": worker.current_action if online else "offline",
        "started_at": worker.started_at,
        "last_heartbeat_at": worker.heartbeat_at,
        "last_news_run_at": worker.last_news_at,
        "last_price_sync_at": worker.last_price_at,
        "iterations": worker.iterations,
        "last_error": worker.last_error,
    }


def agent_live_status() -> dict:
    last_run = AgentRun.objects.first()
    return {
        "running": bool(last_run and last_run.status == AgentRun.STATUS_RUNNING),
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


# ---- worker side (`manage.py run_forever`, its own container) ----


def _update_worker(**fields) -> None:
    AgentWorker.objects.filter(pk=1).update(**fields)


def _heartbeat_loop(stop: threading.Event) -> None:
    # A news run can take minutes; keep the heartbeat fresh meanwhile.
    try:
        while not stop.wait(HEARTBEAT_EVERY_SECONDS):
            _update_worker(heartbeat_at=timezone.now())
    finally:
        connection.close()


def _news_run(config: AgentConfig) -> None:
    _update_worker(current_action="news_run")
    try:
        AgentService(config=config).run()
        _update_worker(last_news_at=timezone.now())
    except Exception as exc:
        _update_worker(last_error=str(exc)[:2000])
        _log_loop_event("worker_news_run_failed", level=AgentLogEvent.LEVEL_WARN, metadata={"error": str(exc)[:2000]})


def _news_thread(config: AgentConfig) -> threading.Thread:
    # A news run (crawl + LLM) takes minutes; run it beside the loop so price
    # syncs keep their interval and charts stay live meanwhile.
    def target():
        try:
            _news_run(config)
        finally:
            connection.close()

    thread = threading.Thread(target=target, name="agent-news", daemon=True)
    thread.start()
    return thread


def _price_sync(config: AgentConfig) -> None:
    try:
        stats = sync_price_feeds(user_agent=config.user_agent)
        _update_worker(last_price_at=timezone.now())
        if stats.errors:
            _log_loop_event(
                "price_sync_errors",
                level=AgentLogEvent.LEVEL_WARN,
                metadata={"errors": stats.errors[:20]},
            )
    except Exception as exc:
        _update_worker(last_error=str(exc)[:2000])
        _log_loop_event("worker_price_sync_failed", level=AgentLogEvent.LEVEL_WARN, metadata={"error": str(exc)[:2000]})


def run_worker(*, max_iterations: Optional[int] = None, sleep: Callable[[float], None] = time.sleep) -> None:
    # ponytail: single worker assumed (one compose replica); add a Postgres
    # advisory lock if this ever runs with more than one replica.
    now = timezone.now()
    # Runs left "running" by a killed worker would show as running forever.
    AgentRun.objects.filter(status=AgentRun.STATUS_RUNNING).update(
        status=AgentRun.STATUS_FAILED, ended_at=now, last_error="worker restarted mid-run"
    )
    _worker_row()
    _update_worker(state="running", current_action="starting", started_at=now, heartbeat_at=now, iterations=0, last_error="")
    _log_loop_event("worker_started")

    stop = threading.Event()
    threading.Thread(target=_heartbeat_loop, args=(stop,), name="agent-heartbeat", daemon=True).start()

    last_news = last_price = float("-inf")
    last_prune_day = None
    iterations = 0
    news = None
    try:
        while max_iterations is None or iterations < max_iterations:
            close_old_connections()
            news_busy = news is not None and news.is_alive()
            today = timezone.now().date()
            if today != last_prune_day:
                last_prune_day = today
                try:
                    _log_loop_event("retention_pruned", metadata=prune_old_data())
                except Exception as exc:
                    _log_loop_event("retention_prune_failed", level=AgentLogEvent.LEVEL_WARN, metadata={"error": str(exc)[:2000]})
            config = get_config()
            if config.run_once_requested and not news_busy:
                AgentConfig.objects.filter(pk=config.pk).update(run_once_requested=False)
                news = _news_thread(config)
                last_news = time.monotonic()
            elif config.run_forever_enabled and not config.run_forever_paused:
                news_interval = max(60.0, float(config.loop_interval_minutes or 15.0) * 60.0)
                price_interval = max(5.0, float(config.price_loop_interval_seconds or 15.0))
                if not news_busy and time.monotonic() - last_news >= news_interval:
                    news = _news_thread(config)
                    last_news = time.monotonic()
                if time.monotonic() - last_price >= price_interval:
                    _price_sync(config)
                    last_price = time.monotonic()
            iterations += 1
            action = "news_run" if news is not None and news.is_alive() else "sleeping"
            _update_worker(current_action=action, heartbeat_at=timezone.now(), iterations=iterations)
            sleep(1.0)
    finally:
        if news is not None:
            news.join()
        stop.set()
        _update_worker(state="stopped", current_action="stopped")
        _log_loop_event("worker_stopped")
