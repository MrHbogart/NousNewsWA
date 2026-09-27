from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import re
from datetime import datetime, timedelta, timezone
from typing import Optional

import httpx
from bs4 import BeautifulSoup
from defusedxml import ElementTree as ET
from django.conf import settings
from django.utils.text import slugify

from agent.models import AgentLogEvent, AgentRun, NewsSource
from dataset.models import RawNewsItem

from .base import SourceFetchResult, SourceSyncStats, _utc_now


class FetchingMixin:
    """Source fetching (RSS/API), item parsing/normalization, dedup, and raw storage."""

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
