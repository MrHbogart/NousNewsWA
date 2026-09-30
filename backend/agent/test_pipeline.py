from datetime import timedelta
from unittest import mock

from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

from agent import price_sync
from agent.models import AgentConfig, AgentRun, PriceSource
from agent.services import AgentService


class PipelineCorrectnessTests(TestCase):
    def test_creating_running_agent_run_does_not_start_a_thread(self):
        with mock.patch("threading.Thread.start") as start:
            AgentRun.objects.create(status=AgentRun.STATUS_RUNNING)
        start.assert_not_called()

    def test_seed_sources_keeps_admin_changes(self):
        call_command("seed_sources", verbosity=0)
        AgentConfig.objects.update(loop_interval_minutes=42.0)
        call_command("seed_sources", verbosity=0)
        self.assertEqual(AgentConfig.objects.get().loop_interval_minutes, 42.0)

    def test_rate_limited_price_source_is_skipped_without_sleeping(self):
        PriceSource.objects.all().delete()
        now = timezone.now()
        PriceSource.objects.create(
            name="slow",
            symbol="X",
            source_type=PriceSource.SOURCE_API,
            base_url="https://example.invalid/price",
            rate_limit_seconds=300,
            last_fetched_at=now - timedelta(seconds=10),
        )
        stats = price_sync.PriceFeedStats()
        with mock.patch("time.sleep") as sleep:
            price_sync._sync_from_price_sources(stats, now)
        sleep.assert_not_called()
        self.assertEqual(stats.feeds_checked, 0)

    def test_run_finalizes_permanent_cards_before_refreshing_open_card(self):
        AgentConfig.objects.create(use_llm_summaries=False)
        service = AgentService()
        calls = []
        stats = mock.Mock(sources_processed=0, items_seen=0, items_saved=0, items_rejected=0)
        with mock.patch.object(service, "_fetch_and_store_sources", return_value=stats), \
             mock.patch.object(service, "_finalize_due_hourly_cards", side_effect=lambda *a: calls.append("hourly") or 0), \
             mock.patch.object(service, "_finalize_due_aggregate_cards", side_effect=lambda *a: calls.append("aggregate") or 0), \
             mock.patch.object(service, "_finalize_due_aftermath_cards", side_effect=lambda *a: calls.append("aftermath") or 0), \
             mock.patch.object(service, "_refresh_current_hour_card", side_effect=lambda *a: calls.append("open_hour")):
            run = service.run()
        self.assertEqual(run.status, AgentRun.STATUS_DONE, run.last_error)
        self.assertEqual(calls, ["hourly", "aggregate", "aftermath", "open_hour"])


class AgentWorkerTests(TestCase):
    def setUp(self):
        self.config = AgentConfig.objects.create(use_llm_summaries=False, loop_interval_minutes=15)

    def _run_worker(self):
        from agent.services import runtime

        # close_old_connections would drop the TestCase transaction's connection.
        with mock.patch.object(runtime, "AgentService") as service_cls, \
             mock.patch.object(runtime, "sync_price_feeds") as prices, \
             mock.patch.object(runtime, "close_old_connections"):
            prices.return_value.errors = []
            runtime.run_worker(max_iterations=1, sleep=lambda _s: None)
        return service_cls, prices

    def test_run_once_runs_while_disabled_and_clears_flag(self):
        from agent.services import runtime

        runtime.request_run_once()
        service_cls, prices = self._run_worker()
        service_cls.return_value.run.assert_called_once()
        prices.assert_not_called()
        self.config.refresh_from_db()
        self.assertFalse(self.config.run_once_requested)

    def test_paused_worker_does_not_run_news(self):
        from agent.services import runtime

        runtime.request_start()
        runtime.request_pause()
        service_cls, _ = self._run_worker()
        service_cls.return_value.run.assert_not_called()
        self.assertEqual(runtime.worker_status()["state"], "paused")

    def test_enabled_worker_runs_news_and_prices(self):
        from agent.services import runtime

        runtime.request_start()
        service_cls, prices = self._run_worker()
        service_cls.return_value.run.assert_called_once()
        prices.assert_called_once()
        status = runtime.worker_status()
        self.assertTrue(status["running"])
        self.assertEqual(status["iterations"], 1)

    def test_stale_heartbeat_reports_not_running(self):
        from agent.models import AgentWorker
        from agent.services import runtime

        runtime.request_start()
        AgentWorker.objects.update_or_create(pk=1, defaults={"heartbeat_at": timezone.now() - timedelta(seconds=31)})
        status = runtime.worker_status()
        self.assertFalse(status["running"])
        self.assertFalse(status["worker_online"])
        self.assertEqual(status["state"], "offline")


RELEVANT_TEXT = (
    "Federal Reserve raises interest rates as inflation stays high; treasury yields, "
    "the dollar, equities and bond markets react to the central bank decision."
)


class CardLifecycleTests(TestCase):
    def setUp(self):
        from articles.models import AssetSeries

        self.config = AgentConfig.objects.create(use_llm_summaries=False, aftermath_min_importance_score=2)
        self.service = AgentService(config=self.config)
        self.now = timezone.now()
        PriceSource.objects.create(name="p", symbol="XAU", chart_label="Gold", source_type=PriceSource.SOURCE_API)
        self.series = AssetSeries.objects.create(symbol="XAU", label="Gold")

    def tearDown(self):
        self.service.close()

    def _final_card(self, period_end, with_data=True):
        from articles.models import AssetCandle, Card, CardArticle, CardAsset

        start = period_end - timedelta(hours=1)
        card = Card.objects.create(
            timeframe=Card.TIMEFRAME_HOUR, period_start=start, period_end=period_end,
            status=Card.STATUS_FINAL, slug=f"hour-{start:%Y%m%d%H%M}", importance_score=3,
        )
        CardArticle.objects.create(card=card, kind=CardArticle.KIND_MAIN, uuid=card.uuid, title="T", summary="S", body="B")
        CardAsset.objects.create(card=card, series=self.series, label="Gold")
        if with_data:
            for minutes, close in ((1, 100.0), (30, 101.0)):
                AssetCandle.objects.create(
                    series=self.series, timestamp=period_end + timedelta(minutes=minutes),
                    open=close, high=close, low=close, close=close,
                )
        return card

    def test_open_card_refresh_keeps_article_slug(self):
        from articles.models import Card

        start = self.now.replace(minute=0, second=0, microsecond=0)
        card = Card.objects.create(
            timeframe=Card.TIMEFRAME_HOUR, period_start=start, period_end=start + timedelta(hours=1),
            status=Card.STATUS_OPEN, slug="hour-open",
        )
        payload = {"title": "First headline", "summary": "", "body": "", "references": [], "impacts": []}
        self.service._upsert_card_articles(card=card, main_payload=dict(payload), side_payloads=[])
        first = card.articles.get(kind="main").slug
        self.service._upsert_card_articles(card=card, main_payload=dict(payload, title="Totally new headline"), side_payloads=[])
        main = card.articles.get(kind="main")
        self.assertEqual(main.slug, first)
        self.assertEqual(main.title, "Totally new headline")

    def test_open_card_refresh_replaces_side_articles(self):
        from articles.models import Card

        start = self.now.replace(minute=0, second=0, microsecond=0)
        card = Card.objects.create(
            timeframe=Card.TIMEFRAME_HOUR, period_start=start, period_end=start + timedelta(hours=1),
            status=Card.STATUS_OPEN, slug="hour-open",
        )
        main = {"title": "Headline", "summary": "", "body": "", "references": [], "impacts": []}
        self.service._upsert_card_articles(card=card, main_payload=dict(main), side_payloads=[{"title": "old side"}])
        self.service._upsert_card_articles(card=card, main_payload=dict(main), side_payloads=[{"title": "new side"}])
        self.assertEqual(list(card.articles.filter(kind="side").values_list("title", flat=True)), ["new side"])

    def test_old_aftermath_candidates_do_not_block_newer_ones(self):
        from articles.models import CardArticle

        old_cards = [self._final_card(self.now - timedelta(days=10, hours=i), with_data=False) for i in range(20)]
        fresh = self._final_card(self.now - timedelta(hours=3))

        created = self.service._finalize_due_aftermath_cards(run=None, now=self.now)

        self.assertEqual(created, 1)
        self.assertTrue(fresh.articles.filter(kind=CardArticle.KIND_AFTERMATH).exists())
        self.assertFalse(CardArticle.objects.filter(card__in=old_cards, kind=CardArticle.KIND_AFTERMATH).exists())

    def test_closed_calendar_day_produces_one_day_card(self):
        from articles.models import Card
        from dataset.models import RawNewsItem

        yesterday = (self.now - timedelta(days=1)).replace(hour=12, minute=0, second=0, microsecond=0)
        for i in range(3):
            RawNewsItem.objects.create(
                source_name="Fed", url=f"https://example.com/{i}", title=f"Fed decision {i}",
                content=RELEVANT_TEXT, cleaned_text=RELEVANT_TEXT, published_at=yesterday + timedelta(minutes=i),
            )
        Card.objects.create(
            timeframe=Card.TIMEFRAME_HOUR, period_start=yesterday, period_end=yesterday + timedelta(hours=1),
            status=Card.STATUS_FINAL, slug="hour-y",
        )

        self.service.run()
        self.service = AgentService(config=self.config)
        self.service.run()

        day_cards = Card.objects.filter(timeframe=Card.TIMEFRAME_DAY)
        self.assertEqual(day_cards.count(), 1)
        card = day_cards.get()
        self.assertEqual(card.slug, f"day-{yesterday:%Y-%m-%d}")
        self.assertEqual(card.status, Card.STATUS_FINAL)


class LlmAndPriceFeedTests(TestCase):
    def test_daily_llm_budget_counts_earlier_runs_today(self):
        config = AgentConfig.objects.create(llm_daily_request_budget=4)
        AgentRun.objects.create(status=AgentRun.STATUS_DONE, llm_requests=3)
        service = AgentService(config=config)
        try:
            self.assertTrue(service._consume_llm_budget(run=None, purpose="a"))
            self.assertFalse(service._consume_llm_budget(run=None, purpose="b"))
        finally:
            service.close()

    def test_run_records_llm_usage(self):
        config = AgentConfig.objects.create(use_llm_summaries=False)
        service = AgentService(config=config)
        service.llm.prompt_tokens, service.llm.completion_tokens = 120, 30
        with mock.patch.object(service, "_fetch_and_store_sources", return_value=mock.Mock(
            sources_processed=0, items_seen=0, items_saved=0, items_rejected=0
        )), mock.patch.object(service, "_consume_llm_budget", wraps=service._consume_llm_budget):
            service.llm_requests_used = 2
            run = service.run()
        run.refresh_from_db()
        self.assertEqual((run.llm_requests, run.llm_prompt_tokens, run.llm_completion_tokens), (2, 120, 30))

    def test_generate_json_rejects_non_object_json(self):
        from agent.llm import LLMClient

        client = LLMClient(AgentConfig.objects.create(llm_api_key="k"))
        body = {"choices": [{"message": {"content": "[1, 2]"}}], "usage": {"prompt_tokens": 5, "completion_tokens": 2}}
        with mock.patch.object(client, "_post_chat", return_value=body):
            self.assertIsNone(client.generate_json("p"))

    def test_auth_header_uses_configured_scheme(self):
        from agent.llm import LLMClient

        config = AgentConfig.objects.create(llm_api_key="k", llm_auth_scheme="apikey")
        self.assertEqual(LLMClient(config)._auth_header(), "apikey k")

    def test_post_chat_accumulates_token_usage(self):
        from agent.llm import LLMClient

        client = LLMClient(AgentConfig.objects.create(llm_api_key="k"))
        response = mock.Mock(status_code=200)
        response.json.return_value = {"choices": [], "usage": {"prompt_tokens": 7, "completion_tokens": 3}}
        with mock.patch("httpx.Client.post", return_value=response):
            client._post_chat({})
            client._post_chat({})
        self.assertEqual((client.prompt_tokens, client.completion_tokens), (14, 6))

    def test_ccxt_uses_usdt_market_and_bar_timestamp(self):
        import sys
        from datetime import datetime, timezone as dt_timezone

        from articles.models import AssetCandle, AssetSeries

        AssetSeries.objects.create(symbol="BTC-USD")
        bar_ms = 1_780_000_020_000
        exchange = mock.Mock()
        exchange.fetch_ohlcv.return_value = [[bar_ms, 1.0, 2.0, 0.5, 1.5, 10.0]]
        fake_ccxt = mock.Mock(binance=mock.Mock(return_value=exchange))
        stats = price_sync.PriceFeedStats()
        with mock.patch.dict(sys.modules, {"ccxt": fake_ccxt}):
            price_sync._sync_from_ccxt(stats, timezone.now())
        exchange.fetch_ohlcv.assert_called_once_with("BTC/USDT", "1m", limit=1)
        candle = AssetCandle.objects.get()
        self.assertEqual(candle.timestamp, datetime.fromtimestamp(bar_ms / 1000, tz=dt_timezone.utc))
        self.assertEqual(candle.close, 1.5)

    def test_price_feed_errors_are_reported(self):
        import sys

        from articles.models import AssetSeries

        AssetSeries.objects.create(symbol="BTC-USD")
        exchange = mock.Mock()
        exchange.fetch_ohlcv.side_effect = RuntimeError("geo-blocked")
        stats = price_sync.PriceFeedStats()
        with mock.patch.dict(sys.modules, {"ccxt": mock.Mock(binance=mock.Mock(return_value=exchange))}):
            price_sync._sync_from_ccxt(stats, timezone.now())
        self.assertTrue(any("geo-blocked" in e for e in stats.errors))

    def test_yfinance_only_requests_mapped_tickers(self):
        from articles.models import AssetSeries

        for symbol in ("XAUUSD=X", "DGS10", "BTC-USD"):
            AssetSeries.objects.create(symbol=symbol)
        self.assertEqual(price_sync._yfinance_targets(), {"XAUUSD=X": "GC=F"})

    def test_price_item_with_published_at_is_stored(self):
        from articles.models import AssetCandle, AssetSeries

        AssetSeries.objects.create(symbol="X")
        source = PriceSource.objects.create(name="rss", symbol="X", source_type=PriceSource.SOURCE_RSS)
        published = timezone.now().replace(second=30)
        recorded = price_sync._store_prices_from_items(source, [{"price": 5.0, "published_at": published}], timezone.now())
        self.assertEqual(recorded, 1)
        self.assertEqual(AssetCandle.objects.get().timestamp, published.replace(second=0, microsecond=0))


class DedupAndRetentionTests(TestCase):
    def test_near_duplicate_titles_across_sources_collapse(self):
        from dataset.models import RawNewsItem

        config = AgentConfig.objects.create()
        published = timezone.now() - timedelta(minutes=10)
        for i, (source, title) in enumerate((("Reuters", "Fed raises rates by 25bp, signals more hikes"),
                                              ("AP", "Fed raises rates by 25 bp; signals more hikes!"),
                                              ("ECB", "ECB holds deposit rate as euro inflation cools"))):
            RawNewsItem.objects.create(
                source_name=source, url=f"https://example.com/{i}", title=title,
                content=RELEVANT_TEXT, cleaned_text=RELEVANT_TEXT, published_at=published + timedelta(seconds=i),
            )
        service = AgentService(config=config)
        try:
            records = service._load_raw_records(published - timedelta(minutes=1), timezone.now())
        finally:
            service.close()
        self.assertEqual(len(records), 2)

    def test_prune_deletes_only_rows_past_retention(self):
        from agent.models import AgentLogEvent
        from agent.retention import prune_old_data
        from articles.models import AssetCandle, AssetSeries
        from dataset.models import RawNewsItem

        now = timezone.now()
        series = AssetSeries.objects.create(symbol="X")
        for age_days in (1, 400):
            when = now - timedelta(days=age_days)
            log = AgentLogEvent.objects.create(step=AgentLogEvent.STEP_LOOP_STATE, message=f"log-{age_days}")
            AgentLogEvent.objects.filter(pk=log.pk).update(created_at=when)
            RawNewsItem.objects.create(source_name="s", url=f"https://e.com/{age_days}", published_at=when)
            AssetCandle.objects.create(series=series, timestamp=when, open=1, high=1, low=1, close=1)

        deleted = prune_old_data(now=now)

        self.assertEqual(deleted, {"logs": 1, "raw_news": 1, "candles": 1})
        self.assertEqual(AgentLogEvent.objects.get().message, "log-1")
        self.assertEqual(RawNewsItem.objects.count(), 1)
        self.assertEqual(AssetCandle.objects.count(), 1)

    def test_worker_prunes_once_per_day(self):
        from agent.services import runtime

        AgentConfig.objects.create()
        with mock.patch.object(runtime, "prune_old_data", return_value={}) as prune, \
             mock.patch.object(runtime, "close_old_connections"):
            runtime.run_worker(max_iterations=3, sleep=lambda _s: None)
        prune.assert_called_once()
