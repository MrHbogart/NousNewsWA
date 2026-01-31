from __future__ import annotations

import csv
import random
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterable, Optional
from urllib.parse import urljoin, urlparse

import httpx
import re
from bs4 import BeautifulSoup
from dateutil import parser as dtparser
from django.conf import settings
from django.db import transaction
from django.db.models import Q

from articles.models import Article
from crawler.llm import LLMClient
from crawler.models import CrawlQueueItem, CrawlRun, CrawlSeed, CrawlerConfig, CrawlLogEvent


@dataclass
class CrawlStats:
    pages_processed: int = 0
    articles_created: int = 0
    queued_urls: int = 0


def get_config() -> CrawlerConfig:
    config = CrawlerConfig.objects.first()
    if config is None:
        config = CrawlerConfig.objects.create()
    return config


class CrawlerService:
    def __init__(self, config: Optional[CrawlerConfig] = None):
        self.config = config or get_config()
        self.client = httpx.Client(
            timeout=getattr(settings, "CRAWLER_FETCH_TIMEOUT_SECONDS", 20),
            headers={"User-Agent": self.config.user_agent},
            follow_redirects=True,
        )
        self.llm = LLMClient(self.config)
        self.log_max_chars = int(getattr(settings, "CRAWLER_LOG_MAX_CHARS", 200000))

    def close(self) -> None:
        self.client.close()

    def run(self, run: Optional[CrawlRun] = None) -> CrawlRun:
        if run is None:
            run = CrawlRun.objects.create(
                status=CrawlRun.STATUS_RUNNING,
            )
        elif run.status != CrawlRun.STATUS_RUNNING:
            run.status = CrawlRun.STATUS_RUNNING
            run.last_error = ""
            run.save(update_fields=["status", "last_error"])
        stats = CrawlStats()
        try:
            self._ensure_seed_queue()
            target_batch_size = max(1, len(self._active_seeds()))
            pages_target = int(self.config.max_pages_per_run)
            unlimited = pages_target <= 0
            page_count = 0
            while True:
                if not unlimited and page_count >= pages_target:
                    break
                seeds = self._active_seeds()
                batch = self._next_pending_batch(seeds, target_batch_size)
                if not batch:
                    break
                processed = self._process_step(batch, stats, run, target_batch_size)
                stats.pages_processed += processed
                page_count += 1
                time.sleep(max(0.0, float(self.config.request_delay_seconds)))
            run.status = CrawlRun.STATUS_DONE
        except Exception as exc:
            run.status = CrawlRun.STATUS_FAILED
            run.last_error = str(exc)[:2000]
        finally:
            run.pages_processed = stats.pages_processed
            run.articles_created = stats.articles_created
            run.queued_urls = stats.queued_urls
            run.ended_at = datetime.now(timezone.utc)
            run.save(update_fields=[
                "status",
                "last_error",
                "pages_processed",
                "articles_created",
                "queued_urls",
                "ended_at",
            ])
            try:
                from articles.services import build_hourly_brief

                build_hourly_brief()
            except Exception as exc:
                self._log_event(
                    run=run,
                    step=CrawlLogEvent.STEP_ERROR,
                    level=CrawlLogEvent.LEVEL_WARN,
                    message="Hourly brief generation failed",
                    content=str(exc),
                )
            self.close()
        return run

    def export_articles_csv(self, writer: csv.writer) -> int:
        rows = Article.objects.order_by("-published_at").values_list(
            "published_at",
            "fetched_at",
            "source",
            "url",
            "title",
            "body",
            "language",
        )
        writer.writerow(["published_at", "fetched_at", "source", "url", "title", "body", "language"])
        count = 0
        for row in rows.iterator():
            writer.writerow(row)
            count += 1
        return count

    def _ensure_seed_queue(self) -> None:
        if CrawlQueueItem.objects.filter(status=CrawlQueueItem.STATUS_PENDING).exists():
            return
        seeds = self._active_seeds()
        for seed in seeds:
            CrawlQueueItem.objects.get_or_create(
                url=seed.url,
                defaults={"seed": seed, "seed_url": seed.url, "depth": 0},
            )

    def _active_seeds(self) -> list[CrawlSeed]:
        return list(
            CrawlSeed.objects.filter(is_active=True).filter(
                Q(config__isnull=True) | Q(config=self.config)
            ).order_by("url")
        )

    def _next_pending_batch(self, seeds: list[CrawlSeed], target_size: int) -> list[CrawlQueueItem]:
        batch: list[CrawlQueueItem] = []
        for seed in seeds:
            item = self._claim_next_pending_for_seed(seed)
            if item:
                batch.append(item)
        if len(batch) < target_size:
            batch.extend(self._claim_next_pending_any(target_size - len(batch), batch))
        return batch

    def _claim_next_pending_for_seed(self, seed: CrawlSeed) -> Optional[CrawlQueueItem]:
        with transaction.atomic():
            item = (
                CrawlQueueItem.objects.select_for_update(skip_locked=True)
                .filter(status=CrawlQueueItem.STATUS_PENDING)
                .filter(Q(seed=seed) | Q(seed__isnull=True, seed_url=seed.url))
                .order_by("discovered_at")
                .first()
            )
            if not item:
                return None
            item.status = CrawlQueueItem.STATUS_IN_PROGRESS
            item.attempts += 1
            item.last_attempt_at = datetime.now(timezone.utc)
            item.save(update_fields=["status", "attempts", "last_attempt_at"])
            return item

    def _claim_next_pending_any(
        self,
        limit: int,
        existing: list[CrawlQueueItem],
    ) -> list[CrawlQueueItem]:
        claimed: list[CrawlQueueItem] = []
        exclude_ids = {item.id for item in existing if item.id}
        for _ in range(limit):
            with transaction.atomic():
                item = (
                    CrawlQueueItem.objects.select_for_update(skip_locked=True)
                    .filter(status=CrawlQueueItem.STATUS_PENDING)
                    .exclude(id__in=exclude_ids)
                    .order_by("discovered_at")
                    .first()
                )
                if not item:
                    break
                item.status = CrawlQueueItem.STATUS_IN_PROGRESS
                item.attempts += 1
                item.last_attempt_at = datetime.now(timezone.utc)
                item.save(update_fields=["status", "attempts", "last_attempt_at"])
                claimed.append(item)
                exclude_ids.add(item.id)
        return claimed

    def _process_step(
        self,
        items: list[CrawlQueueItem],
        stats: CrawlStats,
        run: CrawlRun,
        target_size: int,
    ) -> int:
        seed_payloads = []
        candidate_pool: list[str] = []
        failed_items: list[CrawlQueueItem] = []
        seed_map: dict[str, CrawlSeed] = {}
        seed_depth: dict[str, int] = {}

        for item in items:
            seed_url = item.seed_url or item.url
            if item.seed:
                seed_map[seed_url] = item.seed
            seed_depth[seed_url] = min(item.depth, seed_depth.get(seed_url, item.depth))
            try:
                resp = self.client.get(item.url)
                if resp.status_code >= 400:
                    raise RuntimeError(f"http_{resp.status_code}")

                content_type = resp.headers.get("content-type", "")
                body_chars = len(resp.text or "")
                self._log_event(
                    run=run,
                    item=item,
                    seed_url=seed_url,
                    url=item.url,
                    step=CrawlLogEvent.STEP_FETCH_RESPONSE,
                    message="Fetched response",
                    content=f"status={resp.status_code} content_type={content_type} chars={body_chars}",
                    metadata={
                        "status_code": resp.status_code,
                        "content_type": content_type,
                        "chars": body_chars,
                    },
                )

                cleaned_text = self._clean_html(resp.text)
                if not cleaned_text:
                    raise RuntimeError("empty_context")

                self._log_event(
                    run=run,
                    item=item,
                    seed_url=seed_url,
                    url=item.url,
                    step=CrawlLogEvent.STEP_CLEANED_TEXT,
                    message="Cleaned text",
                    content=cleaned_text,
                    metadata={"chars": len(cleaned_text or "")},
                )

                candidate_urls = self._extract_candidate_urls(resp.text, item.url, seed_url)
                candidate_pool.extend(candidate_urls)
                seed_payloads.append(
                    {
                        "item": item,
                        "seed_url": seed_url,
                        "url": item.url,
                        "html": resp.text,
                        "cleaned_text": cleaned_text,
                        "candidate_urls": candidate_urls,
                    }
                )
            except Exception as exc:
                self._log_event(
                    run=run,
                    item=item,
                    seed_url=seed_url,
                    url=item.url,
                    step=CrawlLogEvent.STEP_ERROR,
                    level=CrawlLogEvent.LEVEL_ERROR,
                    message="Fetch failed",
                    content=str(exc),
                )
                item.status = CrawlQueueItem.STATUS_FAILED
                item.last_error = str(exc)[:2000]
                failed_items.append(item)

        for item in failed_items:
            item.save(update_fields=["status", "last_error"])
            if item.seed:
                item.seed.last_fetched_at = datetime.now(timezone.utc)
                item.seed.last_error = item.last_error or ""
                item.seed.is_active = False
                item.seed.save(update_fields=["last_fetched_at", "last_error", "is_active"])

        if not seed_payloads:
            return len(items)

        seed_urls = [payload["seed_url"] for payload in seed_payloads]
        unique_seed_urls = list(dict.fromkeys(seed_urls))
        context = self._build_context(seed_payloads)
        candidate_block = self._build_candidate_block(seed_payloads)
        prompt = self._build_prompt(
            seed_urls=unique_seed_urls,
            context=context,
            candidate_urls=candidate_block,
            objective=run.objective,
        )

        used_llm = run.use_llm_filtering and self.llm.enabled
        candidate_preview = [u for u in dict.fromkeys(candidate_pool) if u][:20]
        self._log_event(
            run=run,
            step=CrawlLogEvent.STEP_LLM_PROMPT,
            message="LLM context",
            content=context,
            metadata={
                "used_llm": used_llm,
                "seed_urls": unique_seed_urls,
                "candidate_count": len(candidate_pool),
                "candidate_preview": candidate_preview,
                "objective": (run.objective or "").strip(),
            },
        )
        result = self.llm.extract(prompt) if used_llm else None
        if used_llm:
            self._log_event(
                run=run,
                step=CrawlLogEvent.STEP_LLM_OUTPUT,
                message="LLM output",
                content=self.llm.last_output_text,
                metadata={
                    "provider": self.llm.last_provider,
                    "model": self.llm.last_model,
                    "status_code": self.llm.last_status_code,
                    "error": self.llm.last_error,
                },
            )

        if result is None:
            if used_llm:
                self._log_event(
                    run=run,
                    step=CrawlLogEvent.STEP_ERROR,
                    level=CrawlLogEvent.LEVEL_WARN,
                    message="LLM failed, falling back to heuristic extraction",
                    metadata={
                        "provider": self.llm.last_provider,
                        "model": self.llm.last_model,
                        "status_code": self.llm.last_status_code,
                        "error": self.llm.last_error,
                    },
                )
            created = 0
            for payload in seed_payloads:
                payload_articles = self._extract_articles_without_llm(
                    payload["html"],
                    payload["cleaned_text"],
                    payload["url"],
                )
                created += self._store_articles(payload_articles, payload["url"])
            stats.articles_created += created
            next_urls = self._select_next_urls(candidate_pool, limit=target_size)
            selections = self._assign_next_urls(
                [],
                next_urls,
                unique_seed_urls,
                target_size,
                candidate_pool,
            )
        else:
            stats.articles_created += self._store_articles(
                result.articles,
                seed_payloads[0]["url"],
            )
            selections = self._assign_next_urls(
                result.next_urls_by_seed,
                result.next_urls,
                unique_seed_urls,
                target_size,
                candidate_pool,
            )

        added = self._enqueue_next_urls_by_seed(selections, seed_map, seed_depth)
        stats.queued_urls += added
        self._log_event(
            run=run,
            step=CrawlLogEvent.STEP_NEXT_STEP,
            message="Next step selection",
            metadata={
                "queued_urls": added,
                "selections": [{"seed_url": s, "next_url": u} for s, u in selections],
                "articles_created": stats.articles_created,
            },
        )

        for payload in seed_payloads:
            item = payload["item"]
            item.status = CrawlQueueItem.STATUS_DONE
            item.last_error = ""
            item.save(update_fields=["status", "last_error"])
            if item.seed:
                item.seed.last_fetched_at = datetime.now(timezone.utc)
                item.seed.last_error = ""
                item.seed.save(update_fields=["last_fetched_at", "last_error"])

        return len(items)

    def _log_event(
        self,
        *,
        run: Optional[CrawlRun],
        step: str,
        message: str,
        content: str = "",
        metadata: Optional[dict] = None,
        level: str = CrawlLogEvent.LEVEL_INFO,
        item: Optional[CrawlQueueItem] = None,
        seed_url: str = "",
        url: str = "",
    ) -> None:
        if run is None:
            return
        if item:
            seed_url = seed_url or item.seed_url or item.url
            url = url or item.url
        clipped_content, clip_meta = self._clip_log(content)
        meta = dict(metadata or {})
        if clip_meta:
            meta.update(clip_meta)
        CrawlLogEvent.objects.create(
            run=run,
            queue_item=item,
            seed_url=seed_url or "",
            url=url or "",
            step=step,
            level=level,
            message=message,
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

    def _build_context(self, payloads: list[dict]) -> str:
        blocks = []
        for payload in payloads:
            blocks.append(
                f"Seed: {payload['seed_url']}\n"
                f"URL: {payload['url']}\n"
                f"{payload['cleaned_text']}"
            )
        return "\n\n---\n\n".join(blocks)

    def _build_candidate_block(self, payloads: list[dict]) -> str:
        blocks = []
        for payload in payloads:
            urls = payload["candidate_urls"]
            url_block = "\n".join(f"- {u}" for u in list(urls)[:200])
            blocks.append(f"Seed: {payload['seed_url']}\n{url_block or '(none)'}")
        return "\n\n".join(blocks)

    def _build_prompt(
        self,
        *,
        seed_urls: list[str],
        context: str,
        candidate_urls: str,
        objective: str,
    ) -> str:
        prompt = self.config.prompt_template
        seed_block = "\n".join(f"- {u}" for u in seed_urls) or "(none)"
        objective_text = (objective or "").strip()
        if objective_text:
            objective_text = f"Objective:\n{objective_text}\n\n"
        return prompt.format(
            seed_urls=seed_block,
            seed_url=seed_urls[0] if seed_urls else "",
            context=objective_text + context,
            candidate_urls=candidate_urls or "(none)",
            max_next_urls=self.config.max_next_urls,
            max_articles=self.config.max_articles,
            max_article_chars=self.config.max_article_chars,
        )

    def _assign_next_urls(
        self,
        next_urls_by_seed: list[dict],
        next_urls: list[str],
        seed_urls: list[str],
        target_size: int,
        candidate_pool: list[str],
    ) -> list[tuple[str, str]]:
        seed_urls = [u for u in seed_urls if u]
        if not seed_urls:
            return []
        mapping: dict[str, str] = {}
        for entry in next_urls_by_seed or []:
            seed_url = (entry.get("seed_url") or "").strip()
            next_url = (entry.get("next_url") or "").strip()
            if seed_url and next_url and seed_url in seed_urls:
                mapping[seed_url] = next_url

        selections: list[tuple[str, str]] = []
        used_urls = set()
        for seed_url in seed_urls:
            if seed_url in mapping and mapping[seed_url] not in used_urls:
                selections.append((seed_url, mapping[seed_url]))
                used_urls.add(mapping[seed_url])

        if not selections and next_urls:
            for idx, url in enumerate(next_urls):
                url = (url or "").strip()
                if not url or url in used_urls:
                    continue
                seed_url = seed_urls[idx % len(seed_urls)]
                selections.append((seed_url, url))
                used_urls.add(url)

        fallback = [
            u for u in self._select_next_urls(candidate_pool, limit=target_size) if u not in used_urls
        ]
        seed_index = 0
        while len(selections) < target_size and fallback:
            url = fallback.pop(0)
            seed_url = seed_urls[seed_index % len(seed_urls)]
            seed_index += 1
            if url in used_urls:
                continue
            selections.append((seed_url, url))
            used_urls.add(url)
        return selections

    def _enqueue_next_urls_by_seed(
        self,
        selections: list[tuple[str, str]],
        seed_map: dict[str, CrawlSeed],
        seed_depth: dict[str, int],
    ) -> int:
        count = 0
        for seed_url, url in selections:
            seed = seed_map.get(seed_url)
            depth = seed_depth.get(seed_url, 0)
            if self.config.max_depth > 0 and depth >= self.config.max_depth:
                continue
            url = (url or "").strip()
            if not url:
                continue
            if not url.startswith(("http://", "https://")):
                url = urljoin(seed_url, url)
            _, created = CrawlQueueItem.objects.get_or_create(
                url=url,
                defaults={
                    "seed": seed,
                    "seed_url": seed_url,
                    "depth": depth + 1,
                },
            )
            if created:
                count += 1
        return count

    def _select_next_urls(self, candidate_urls: Iterable[str], limit: Optional[int] = None) -> list[str]:
        seen = set()
        urls = []
        for url in candidate_urls:
            if not url or url in seen:
                continue
            if not self._is_useful_url(url):
                continue
            seen.add(url)
            urls.append(url)
        random.shuffle(urls)
        if limit is None:
            limit = self.config.max_next_urls
        limit = max(1, int(limit))
        return urls[:limit]

    def _is_useful_url(self, url: str) -> bool:
        lowered = url.lower()
        skip_tokens = [
            "/login",
            "/signup",
            "/register",
            "/account",
            "/privacy",
            "/terms",
            "/cookie",
            "/contact",
            "/about",
            "/help",
            "/support",
            "/advertise",
            "/subscribe",
            "/newsletter",
            "/rss",
        ]
        if any(token in lowered for token in skip_tokens):
            return False
        return True

    def _extract_articles_without_llm(
        self,
        html: str,
        cleaned_text: str,
        source_url: str,
    ) -> list[dict]:
        soup = BeautifulSoup(html or "", "html.parser")
        title = self._extract_title(soup) or ""
        published_at = self._extract_published_at(soup)
        body = self._extract_body_text(soup)
        if not body:
            body = cleaned_text
        body = self._clip_text(body, self.config.max_article_chars)
        if not title and not body:
            return []
        return [
            {
                "url": source_url,
                "title": title,
                "published_at": published_at.isoformat() if published_at else None,
                "source": urlparse(source_url).netloc,
                "body": body,
            }
        ]

    def _extract_title(self, soup: BeautifulSoup) -> str:
        meta = soup.find("meta", attrs={"property": "og:title"})
        if meta and meta.get("content"):
            return meta["content"].strip()
        meta = soup.find("meta", attrs={"name": "twitter:title"})
        if meta and meta.get("content"):
            return meta["content"].strip()
        if soup.title and soup.title.string:
            return soup.title.string.strip()
        return ""

    def _extract_published_at(self, soup: BeautifulSoup) -> Optional[datetime]:
        meta = soup.find("meta", attrs={"property": "article:published_time"})
        if meta and meta.get("content"):
            return self._parse_datetime(meta["content"])
        time_tag = soup.find("time")
        if time_tag and time_tag.get("datetime"):
            return self._parse_datetime(time_tag["datetime"])
        return None

    def _extract_body_text(self, soup: BeautifulSoup) -> str:
        candidate = soup.find("article")
        if candidate is None:
            candidate = soup.find("main")
        if candidate is None:
            candidate = soup.body or soup
        paragraphs = [p.get_text(" ", strip=True) for p in candidate.find_all("p")]
        filtered = [p for p in paragraphs if len(p) >= 40]
        if not filtered:
            filtered = [p for p in paragraphs if p]
        return "\n\n".join(filtered)

    def _clean_html(self, html: str) -> str:
        soup = BeautifulSoup(html or "", "html.parser")
        for tag in soup(["script", "style", "noscript", "header", "footer", "nav", "aside", "form"]):
            tag.decompose()
        text = soup.get_text(" ")
        text = re.sub(r"\s+", " ", text)
        text = re.sub(r"[\\u00A0\\t]+", " ", text).strip()
        sentences = [s.strip() for s in text.split(".") if s.strip()]
        if sentences:
            compact = ". ".join(sentences)
        else:
            compact = text
        return self._clip_text(compact, self.config.max_context_chars)

    def _clip_text(self, text: str, max_chars: int) -> str:
        if max_chars <= 0 or len(text) <= max_chars:
            return text
        head = int(max_chars * 0.7)
        tail = max_chars - head
        return text[:head] + "\n...\n" + text[-tail:]

    def _extract_candidate_urls(self, html: str, base_url: str, seed_url: str) -> list[str]:
        soup = BeautifulSoup(html or "", "html.parser")
        out = []
        seed_domain = urlparse(seed_url).netloc
        for a in soup.find_all("a", href=True):
            href = a["href"].strip()
            if not href:
                continue
            absolute = urljoin(base_url, href)
            parsed = urlparse(absolute)
            if not parsed.scheme.startswith("http"):
                continue
            if not self.config.allow_external_domains and parsed.netloc != seed_domain:
                continue
            if absolute not in out:
                out.append(absolute)
        return out

    def _store_articles(self, articles: Iterable[dict], source_url: str) -> int:
        created = 0
        for entry in articles:
            url = (entry.get("url") or "").strip()
            if not url:
                url = source_url
            if not url.startswith(("http://", "https://")):
                url = urljoin(source_url, url)
            title = (entry.get("title") or "").strip()
            body = (entry.get("body") or "").strip()
            if not title and not body:
                continue
            if not self._is_article_quality(title, body):
                continue
            body = body[: self.config.max_article_chars]
            published_at = self._parse_datetime(entry.get("published_at"))
            if published_at is None:
                published_at = datetime.now(timezone.utc)
            source = (entry.get("source") or "").strip() or urlparse(url).netloc
            article, created_flag = Article.objects.update_or_create(
                url=url,
                defaults={
                    "source": source,
                    "published_at": published_at,
                    "fetched_at": datetime.now(timezone.utc),
                    "title": title,
                    "body": body,
                    "language": "",
                },
            )
            if created_flag:
                created += 1
        return created

    def _is_article_quality(self, title: str, body: str) -> bool:
        body_text = body.strip()
        title_text = title.strip()
        if not body_text:
            return False
        if len(body_text) < 200 and len(title_text) < 15:
            return False
        lowered = f"{title_text}\n{body_text}".lower()
        junk_markers = [
            "301 moved permanently",
            "302 found",
            "403 forbidden",
            "404 not found",
            "500 internal server error",
            "nginx",
            "cloudflare",
            "access denied",
            "captcha",
            "enable javascript",
            "service unavailable",
        ]
        if any(marker in lowered for marker in junk_markers):
            return False
        alpha_chars = sum(1 for ch in body_text if ch.isalpha())
        if alpha_chars / max(1, len(body_text)) < 0.5:
            return False
        return True

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


RUN_LOCK = threading.Lock()
RUN_THREAD: Optional[threading.Thread] = None
RUN_ACTIVE = False
RUN_LAST_ERROR = ""


def start_crawler_async(run_id: Optional[int] = None) -> bool:
    global RUN_THREAD, RUN_ACTIVE, RUN_LAST_ERROR
    with RUN_LOCK:
        if RUN_THREAD and RUN_THREAD.is_alive():
            return False

        RUN_ACTIVE = True
        RUN_LAST_ERROR = ""

        def _runner() -> None:
            global RUN_ACTIVE, RUN_LAST_ERROR
            try:
                service = CrawlerService()
                run = None
                if run_id is not None:
                    run = CrawlRun.objects.filter(pk=run_id).first()
                service.run(run)
            except Exception as exc:
                RUN_LAST_ERROR = str(exc)[:2000]
            finally:
                RUN_ACTIVE = False

        RUN_THREAD = threading.Thread(target=_runner, name="crawler-runner", daemon=True)
        RUN_THREAD.start()
        return True


def crawler_live_status() -> dict:
    last_run = CrawlRun.objects.first()
    return {
        "running": RUN_ACTIVE,
        "last_error": RUN_LAST_ERROR,
        "last_run": {
            "status": last_run.status,
            "started_at": last_run.started_at,
            "ended_at": last_run.ended_at,
            "pages_processed": last_run.pages_processed,
            "articles_created": last_run.articles_created,
            "queued_urls": last_run.queued_urls,
            "last_error": last_run.last_error,
        } if last_run else None,
        "queue": {
            "pending": CrawlQueueItem.objects.filter(status=CrawlQueueItem.STATUS_PENDING).count(),
            "in_progress": CrawlQueueItem.objects.filter(status=CrawlQueueItem.STATUS_IN_PROGRESS).count(),
            "done": CrawlQueueItem.objects.filter(status=CrawlQueueItem.STATUS_DONE).count(),
            "failed": CrawlQueueItem.objects.filter(status=CrawlQueueItem.STATUS_FAILED).count(),
        },
    }
