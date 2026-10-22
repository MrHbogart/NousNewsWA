from __future__ import annotations

from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import ipaddress
import os
import re
import socket
from datetime import datetime, timedelta, timezone
from typing import Optional
from urllib.parse import urlparse

import httpx
from bs4 import BeautifulSoup
from defusedxml import ElementTree as ET
from django.conf import settings
from django.utils.text import slugify

from agent.models import AgentLogEvent, AgentRun, NewsSource
from dataset.models import RawNewsItem

from .base import SourceFetchResult, SourceSyncStats, _utc_now


FULLTEXT_MIN_CHARS = 500
FULLTEXT_MAX_CHARS = 6000
FULLTEXT_MAX_BYTES = 3_000_000
# Pages that never yield article text (JS redirects).
FULLTEXT_SKIP_HOSTS = {"news.google.com"}
FULLTEXT_SKIP_EXTENSIONS = (".pdf", ".xls", ".xlsx", ".csv", ".zip", ".doc", ".docx", ".mp4", ".mp3")


# URLs the LLM filter rejected, so a feed that keeps listing an item for a
# day doesn't get it re-reviewed (and re-billed) every run. Per worker process.
_LLM_REJECTED_MAX = 20000
_llm_rejected_urls: OrderedDict[str, None] = OrderedDict()


def _remember_rejected(url: str) -> None:
    _llm_rejected_urls[url] = None
    while len(_llm_rejected_urls) > _LLM_REJECTED_MAX:
        _llm_rejected_urls.popitem(last=False)


def resolve_public_url(url: str) -> tuple[str, str, str] | None:
    """(URL with the host replaced by its checked IP, Host header, hostname), or None.

    None unless the URL is http(s) and every address the name resolves to is public.
    """
    parsed = urlparse(url or "")
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        return None
    default_port = 443 if parsed.scheme == "https" else 80
    try:
        port = parsed.port or default_port
        infos = socket.getaddrinfo(parsed.hostname, port, type=socket.SOCK_STREAM)
    except (OSError, ValueError):
        return None
    addresses = [info[4][0] for info in infos]
    if not addresses or not all(_is_public_address(a) for a in addresses):
        return None
    ip = addresses[0].split("%", 1)[0]
    netloc = f"[{ip}]" if ":" in ip else ip
    if parsed.port:
        netloc += f":{parsed.port}"
    host_header = parsed.hostname + (f":{parsed.port}" if parsed.port and parsed.port != default_port else "")
    return parsed._replace(netloc=netloc).geturl(), host_header, parsed.hostname


def is_public_http_url(url: str) -> bool:
    """http(s) URL whose host resolves only to public addresses."""
    return resolve_public_url(url) is not None


# Fake-IP DNS proxies (Clash and similar) answer every name from the benchmark
# range. Opt in with AGENT_FETCH_ALLOW_FAKE_IP=true only on such a host; then
# the proxy, not this check, decides what is reachable.
_FAKE_IP_NETWORK = ipaddress.ip_network("198.18.0.0/15")
_ALLOW_FAKE_IP = os.getenv("AGENT_FETCH_ALLOW_FAKE_IP", "false").strip().lower() == "true"


def _is_public_address(address: str) -> bool:
    ip = ipaddress.ip_address(address.split("%", 1)[0])
    return ip.is_global or (_ALLOW_FAKE_IP and ip in _FAKE_IP_NETWORK)



def _local(tag: object) -> str:
    return tag.rsplit("}", 1)[-1] if isinstance(tag, str) else ""


def _child_text(node, *names: str) -> str:
    for name in names:
        for child in node:
            if _local(child.tag) == name and (child.text or "").strip():
                return child.text.strip()
    return ""


def parse_feed(xml_text: str) -> list[dict]:
    """Items of an RSS 2.0, RSS 1.0 (RDF) or Atom feed, whatever namespaces it uses.

    Returns {title, summary, content, url, published} with `published` unparsed.
    """
    try:
        root = ET.fromstring(xml_text)
    except Exception:
        return []
    items = []
    for node in root.iter():
        if _local(node.tag) not in ("item", "entry"):
            continue
        title = _child_text(node, "title")
        summary = _child_text(node, "description", "summary")
        url = ""
        for child in node:
            if _local(child.tag) == "link":
                url = (child.attrib.get("href") or child.text or "").strip()
                if url and child.attrib.get("rel", "alternate") == "alternate":
                    break
        items.append(
            {
                "title": title,
                "summary": summary,
                "content": _child_text(node, "encoded", "content") or summary or title,
                "url": url,
                "published": _child_text(node, "pubDate", "published", "updated", "date", "issued"),
            }
        )
    return items


def extract_article_text(html: str) -> str:
    """Main paragraphs of an article page; "" when it doesn't look like an article."""
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "noscript", "nav", "header", "footer", "aside", "form", "figure"]):
        tag.decompose()
    root = soup.find("article") or soup.find("main") or soup.body or soup
    paragraphs = [p.get_text(" ", strip=True) for p in root.find_all("p")]
    text = "\n\n".join(p for p in paragraphs if len(p) >= 60)
    return text[:FULLTEXT_MAX_CHARS] if len(text) >= 400 else ""


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
            active_sources.append(source)

        if not active_sources:
            return stats

        # 1) Fetch every source concurrently, then run cheap per-item checks.
        candidates: list[dict] = []
        per_source: dict[int, dict] = {}
        seen_keys: set[str] = set()
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
                            "failure_count": source.failure_count,
                            "backoff_until": source.backoff_until,
                        },
                    )
                    continue

                counts = per_source[source.id] = {
                    "source": source,
                    "duration_ms": fetched.duration_ms,
                    "items_seen": 0,
                    "items_saved": 0,
                    "items_rejected": 0,
                    "items_rejected_old": 0,
                    "items_rejected_llm": 0,
                    "items_already_stored": 0,
                }
                # Items stored by an earlier run: skip before scoring so they
                # don't spend LLM filter budget again every run.
                stored_urls = set(
                    RawNewsItem.objects.filter(
                        url__in=[(item.get("url") or "").strip() for item in fetched.items if item.get("url")]
                    ).values_list("url", flat=True)
                )
                source_latest: Optional[datetime] = None
                is_aggregator = (urlparse(source.base_url).hostname or "") == "news.google.com"
                for item in fetched.items:
                    counts["items_seen"] += 1
                    stats.items_seen += 1
                    url = (item.get("url") or "").strip()
                    if url in stored_urls or url in _llm_rejected_urls:
                        counts["items_already_stored"] += 1
                        continue

                    title = (item.get("title") or "").strip()
                    if is_aggregator:
                        title = title.rsplit(" - ", 1)[0]  # "Headline - Publisher"
                    summary = (item.get("summary") or "").strip()
                    content = (item.get("content") or "").strip()
                    cleaned = self._clean_text(content or summary or title)
                    published_dt = self._parse_datetime(item.get("published_at"))
                    if not cleaned or not published_dt:
                        counts["items_rejected"] += 1
                        continue
                    if self._current_run_min_published_at and published_dt < self._current_run_min_published_at:
                        counts["items_rejected"] += 1
                        counts["items_rejected_old"] += 1
                        continue
                    if source_latest is None or published_dt > source_latest:
                        source_latest = published_dt
                    # Across sources too: aggregators repeat the same link.
                    dedupe_key = self._dedupe_key(item, title, published_dt)
                    if dedupe_key in seen_keys:
                        counts["items_rejected"] += 1
                        continue
                    seen_keys.add(dedupe_key)

                    candidates.append(
                        {
                            "source": source,
                            "source_name": source.name,
                            "title": title,
                            "summary": summary,
                            "content": content,
                            "cleaned": cleaned,
                            "url": url,
                            "published_at": published_dt,
                            "score": self._relevance_score(cleaned, title),
                        }
                    )

                self._record_source_success(source, source_latest or now)

        # 2) Relevance: the LLM judges borderline-and-up items in batches; the
        # heuristic decides the rest (and everything when the LLM is off or out of budget).
        floor = self._MIN_RELEVANCE_SCORE - self._LLM_FILTER_SCORE_BUFFER
        reviewable = [c for c in candidates if c["score"] >= floor]
        decisions = self._llm_filter_batch(run, reviewable)
        llm_verdict = {id(c): decisions[i] for i, c in enumerate(reviewable) if i in decisions}
        accepted = []
        for candidate in candidates:
            verdict = llm_verdict.get(id(candidate))
            counts = per_source[candidate["source"].id]
            if verdict is False:
                counts["items_rejected"] += 1
                counts["items_rejected_llm"] += 1
                if candidate["url"]:
                    _remember_rejected(candidate["url"])
            elif verdict or candidate["score"] >= self._MIN_RELEVANCE_SCORE:
                accepted.append(candidate)
            else:
                counts["items_rejected"] += 1

        # 3) Feeds often carry a one-line teaser: fetch the page for those.
        enriched = self._enrich_full_text(accepted)

        for candidate in accepted:
            self._store_raw_item(
                candidate["source"],
                {
                    "title": candidate["title"],
                    "summary": candidate["summary"],
                    "content": candidate["content"],
                    "url": candidate["url"],
                    "published_at": candidate["published_at"],
                },
                candidate["cleaned"],
            )
            per_source[candidate["source"].id]["items_saved"] += 1
            stats.items_saved += 1

        for counts in per_source.values():
            source = counts.pop("source")
            stats.items_rejected += counts["items_rejected"]
            self._log_event(
                run=run,
                step=AgentLogEvent.STEP_SOURCE_FETCH,
                message="source_fetch_completed",
                metadata={
                    "source": source.name,
                    **counts,
                    "min_published_at": self._current_run_min_published_at,
                },
            )
        if enriched:
            self._log_event(
                run=run,
                step=AgentLogEvent.STEP_SOURCE_FETCH,
                message="full_text_fetched",
                metadata={"items": enriched},
            )

        return stats

    def _enrich_full_text(self, candidates: list[dict]) -> int:
        """Replace teaser text with the article page's text; best effort, capped per run."""
        targets = [
            c
            for c in candidates
            if len(c["cleaned"]) < FULLTEXT_MIN_CHARS
            and c["url"].startswith("http")
            and (urlparse(c["url"]).hostname or "") not in FULLTEXT_SKIP_HOSTS
            and not urlparse(c["url"]).path.lower().endswith(FULLTEXT_SKIP_EXTENSIONS)
        ][: self._FULLTEXT_MAX_PER_RUN]
        if not targets:
            return 0
        with ThreadPoolExecutor(max_workers=min(8, len(targets)), thread_name_prefix="full-text") as executor:
            texts = list(executor.map(self._fetch_article_text, [c["url"] for c in targets]))
        enriched = 0
        for candidate, text in zip(targets, texts):
            if len(text) > len(candidate["cleaned"]):
                candidate["content"] = candidate["cleaned"] = text
                enriched += 1
        return enriched

    def _fetch_article_text(self, url: str) -> str:
        # Feed links are third-party input: follow redirects by hand so every
        # hop is checked to be a public address (no internal services).
        client = httpx.Client(
            timeout=getattr(settings, "AGENT_FETCH_TIMEOUT_SECONDS", 20),
            headers={"User-Agent": self.config.user_agent},
            follow_redirects=False,
        )
        try:
            for _ in range(4):
                # Connect to the address that was checked (no second DNS lookup
                # to rebind); Host and TLS SNI keep the real name, so the
                # certificate is still verified against it.
                pinned = resolve_public_url(url)
                if pinned is None:
                    return ""
                pinned_url, host_header, hostname = pinned
                with client.stream(
                    "GET", pinned_url, headers={"Host": host_header}, extensions={"sni_hostname": hostname}
                ) as resp:
                    if resp.is_redirect:
                        location = resp.headers.get("location", "")
                        url = str(httpx.URL(url).join(location)) if location else ""
                        continue
                    if resp.status_code >= 400 or "html" not in resp.headers.get("content-type", ""):
                        return ""
                    if int(resp.headers.get("content-length") or 0) > FULLTEXT_MAX_BYTES:
                        return ""
                    body = bytearray()
                    for chunk in resp.iter_bytes():
                        body += chunk
                        if len(body) >= FULLTEXT_MAX_BYTES:
                            break
                    return extract_article_text(bytes(body).decode(resp.encoding or "utf-8", errors="replace"))
            return ""
        except Exception:
            return ""
        finally:
            client.close()

    def _fetch_api_source(self, source: NewsSource, *, client: Optional[httpx.Client] = None) -> list[dict]:
        api_key = source.resolved_api_key
        if source.requires_api_key and not api_key:
            raise RuntimeError("missing_api_key")
        params = {}
        headers = {}
        if source.api_key_header and api_key:
            headers[source.api_key_header] = api_key
        if source.api_key_param and api_key:
            params[source.api_key_param] = api_key
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
        return items[: int(self.config.max_items_per_source)]

    def _fetch_rss_source(self, source: NewsSource, *, client: Optional[httpx.Client] = None) -> list[dict]:
        http_client = client or self.client
        resp = http_client.get(source.base_url)
        if resp.status_code == 429:
            raise RuntimeError("rate_limited")
        if resp.status_code >= 400:
            raise RuntimeError(f"http_{resp.status_code}")
        items = self._parse_rss_items(resp.text)
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
        return [dict(item, published_at=self._parse_datetime(item.pop("published"))) for item in parse_feed(xml_text)]

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

    def _format_since(self, value: datetime, fmt: str) -> str:
        if fmt == "unix":
            return str(int(value.timestamp()))
        if fmt == "rfc3339":
            return value.isoformat()
        return value.isoformat()

    def _record_source_success(self, source: NewsSource, latest: datetime) -> None:
        source.last_fetched_at = latest
        source.failure_count = 0
        source.last_error = ""
        # rate_limit_seconds is the minimum gap between fetches (quota-limited APIs).
        source.backoff_until = (
            _utc_now() + timedelta(seconds=source.rate_limit_seconds) if source.rate_limit_seconds >= 60 else None
        )
        source.save(update_fields=["last_fetched_at", "failure_count", "last_error", "backoff_until"])

    def _record_source_error(self, source: NewsSource, error: str) -> None:
        # 15, 30, 60 ... minutes, capped at 6 hours: a dead feed stops costing a request every run.
        source.failure_count += 1
        source.last_error = error[:2000]
        minutes = min(360, 15 * 2 ** min(source.failure_count - 1, 5))
        if error == "rate_limited":
            minutes = max(minutes, int(source.rate_limit_seconds or 0) // 60, 1)
        source.backoff_until = _utc_now() + timedelta(minutes=minutes)
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
