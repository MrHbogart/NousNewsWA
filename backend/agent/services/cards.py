from __future__ import annotations

import re
from datetime import datetime, timedelta
from difflib import SequenceMatcher
from typing import Optional
from uuid import uuid4

from django.db import transaction

from agent.models import AgentLogEvent, AgentRun
from articles.models import AssetSeries, Card, CardArticle, CardAsset
from articles.services import enabled_price_source_labels, get_period_window
from articles.slugging import build_article_slug
from dataset.models import RawNewsItem


def _title_key(title: str) -> str:
    return re.sub(r"[^a-z0-9]", "", title.lower())


class CardsMixin:
    """Card/period lifecycle: loading raw records for a window and upserting Card/CardArticle/CardAsset."""

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

        # One transaction: SSE readers never see new articles on a stale card.
        with transaction.atomic():
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
            # One transaction: SSE readers never see new articles on a stale card.
            with transaction.atomic():
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
        for timeframe in (Card.TIMEFRAME_DAY, Card.TIMEFRAME_WEEK, Card.TIMEFRAME_MONTH):
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

                # One transaction: SSE readers never see new articles on a stale card.
                with transaction.atomic():
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

    def _aftermath_delay_minutes(self, timeframe: str) -> int:
        return {
            Card.TIMEFRAME_HOUR: self.config.aftermath_delay_hour_minutes,
            Card.TIMEFRAME_DAY: self.config.aftermath_delay_day_minutes,
            Card.TIMEFRAME_WEEK: self.config.aftermath_delay_week_minutes,
            Card.TIMEFRAME_MONTH: self.config.aftermath_delay_month_minutes,
        }.get(timeframe, self.config.aftermath_delay_hour_minutes)

    def _finalize_due_aftermath_cards(self, run: AgentRun, now: datetime) -> int:
        min_score = self.config.aftermath_min_importance_score
        candidates = (
            # Only recent cards that track assets: a card with no price data
            # retries until it ages out instead of blocking the queue forever.
            Card.objects.filter(
                status=Card.STATUS_FINAL,
                importance_score__gte=min_score,
                period_end__gte=now - timedelta(days=self._AFTERMATH_MAX_AGE_DAYS),
                assets__isnull=False,
            )
            .exclude(articles__kind=CardArticle.KIND_AFTERMATH)
            .distinct()
            .prefetch_related("articles")
            .order_by("period_start")[: self._MAX_AGGREGATE_BACKFILL_PERIODS]
        )

        created = 0
        for card in candidates:
            delay_minutes = self._aftermath_delay_minutes(card.timeframe)
            price_window_end = card.period_end + timedelta(minutes=delay_minutes)
            if now < price_window_end:
                continue

            main_article = next((a for a in card.articles.all() if a.kind == CardArticle.KIND_MAIN), None)
            if main_article is None:
                continue

            payload = self._build_aftermath_payload(
                card=card,
                main_article=main_article,
                price_window_end=price_window_end,
                run=run,
            )
            if payload is None:
                continue

            self._upsert_aftermath_article(card=card, payload=payload, price_window_end=price_window_end)
            created += 1
            self._log_event(
                run=run,
                step=AgentLogEvent.STEP_CARD_GENERATION,
                message="aftermath_card_finalized",
                metadata={
                    "card_slug": card.slug,
                    "timeframe": card.timeframe,
                    "price_window_end": price_window_end,
                    "title": payload.get("title"),
                },
            )

        return created

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
            return start.strftime("day-%Y-%m-%d")
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
        fields = {
            "title": main_title,
            "summary": main_payload.get("summary") or "",
            "body": main_payload.get("body") or "",
            "references": self._normalize_references(main_payload.get("references")),
            "impacts": main_payload.get("impacts") or [],
            "time_window": card.timeframe,
            "published_at": card.published_at,
        }
        main_article = card.articles.filter(kind=CardArticle.KIND_MAIN).first()
        if main_article is None:
            # The slug is fixed at creation so shared URLs never change,
            # even when an open card's headline is rewritten later.
            main_article = CardArticle.objects.create(
                card=card,
                kind=CardArticle.KIND_MAIN,
                uuid=card.uuid,
                slug=build_article_slug(
                    title=main_title,
                    period_start=card.period_start,
                    article_uuid=card.uuid,
                    kind=CardArticle.KIND_MAIN,
                ),
                **fields,
            )
        else:
            for key, value in fields.items():
                setattr(main_article, key, value)
            main_article.save(update_fields=[*fields, "updated_at"])

        # keep payload slug aligned with persisted article slug
        main_payload["slug"] = main_article.slug

        card.articles.filter(kind=CardArticle.KIND_SIDE).delete()
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

    def _upsert_aftermath_article(self, *, card: Card, payload: dict, price_window_end: datetime) -> None:
        title = payload.get("title") or "Post-brief price check"
        article_uuid = uuid4()
        CardArticle.objects.update_or_create(
            card=card,
            kind=CardArticle.KIND_AFTERMATH,
            defaults={
                "uuid": article_uuid,
                "slug": build_article_slug(
                    title=title,
                    period_start=card.period_start,
                    article_uuid=article_uuid,
                    kind=CardArticle.KIND_AFTERMATH,
                ),
                "title": title,
                "summary": payload.get("summary") or "",
                "body": payload.get("body") or "",
                "references": self._normalize_references(payload.get("references")),
                "impacts": [],
                "time_window": card.timeframe,
                "published_at": price_window_end,
                "aftermath_price_until": price_window_end,
            },
        )

    def _ensure_card_assets(self, card: Card) -> None:
        enabled_symbol_labels = enabled_price_source_labels()
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

    def _load_raw_records(self, start: datetime, end: datetime) -> list[dict]:
        qs = RawNewsItem.objects.filter(published_at__gte=start, published_at__lt=end).order_by("-published_at")
        records = []
        seen = set()
        kept_titles: list[str] = []
        for raw in qs:
            # Stored rows already passed the relevance gate at ingest (heuristic
            # or LLM); re-scoring here used to drop every LLM-accepted item.
            cleaned = raw.cleaned_text or self._clean_text(raw.content or raw.summary or raw.title)
            key = self._dedupe_key({"url": raw.url}, raw.title, raw.published_at)
            if key in seen:
                continue
            seen.add(key)
            title_key = _title_key(raw.title or "")
            # ponytail: compares against the newest 200 kept titles only (rows are
            # newest-first, so duplicates sit close together); keeps month cards
            # O(200n) instead of O(n^2). Use a minhash index if that misses dupes.
            if title_key and any(
                SequenceMatcher(None, title_key, kept).ratio() >= 0.85 for kept in kept_titles[-200:]
            ):
                continue
            kept_titles.append(title_key)
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
