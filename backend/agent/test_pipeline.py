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
             mock.patch.object(service, "_finalize_due_cards", side_effect=lambda *a: calls.append("final") or 0), \
             mock.patch.object(service, "_finalize_due_aftermath_cards", side_effect=lambda *a: calls.append("aftermath") or 0), \
             mock.patch.object(service, "_refresh_current_intraday_card", side_effect=lambda *a: calls.append("open")):
            run = service.run()
        self.assertEqual(run.status, AgentRun.STATUS_DONE, run.last_error)
        self.assertEqual(calls, ["final", "aftermath", "open"])


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
            timeframe=Card.TIMEFRAME_INTRADAY, period_start=start, period_end=period_end,
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
            timeframe=Card.TIMEFRAME_INTRADAY, period_start=start, period_end=start + timedelta(hours=1),
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
            timeframe=Card.TIMEFRAME_INTRADAY, period_start=start, period_end=start + timedelta(hours=1),
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
            timeframe=Card.TIMEFRAME_INTRADAY, period_start=yesterday, period_end=yesterday + timedelta(hours=1),
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

        # The migrated 1-hour card at 12:00 was rebuilt as the 12:00-16:00 block.
        block = Card.objects.get(timeframe=Card.TIMEFRAME_INTRADAY, period_start=yesterday)
        self.assertEqual(block.period_end, yesterday + timedelta(hours=4))
        self.assertEqual(block.status, Card.STATUS_FINAL)
        self.assertTrue(block.articles.filter(kind="main").exists())


class LlmAndPriceFeedTests(TestCase):
    def setUp(self):
        price_sync._ccxt_paused_until = 0.0  # module state: an earlier failure pauses ccxt

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
        exchange.fetch_ohlcv.assert_called_once_with("BTC/USDT", "1m", limit=1000)
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


class ProductionReviewFixTests(TestCase):
    def test_keywords_match_whole_words_only(self):
        from agent.services.scoring import _mentions

        self.assertFalse(_mentions("fierce competition for capital allocation", "pet"))
        self.assertFalse(_mentions("fierce competition for capital allocation", "cat"))
        self.assertTrue(_mentions("treasury yields jumped", "yield"))
        self.assertTrue(_mentions("new tariffs announced", "tariff"))

    def test_llm_accepted_low_score_item_is_used_for_the_card(self):
        from dataset.models import RawNewsItem

        config = AgentConfig.objects.create()
        published = timezone.now() - timedelta(minutes=5)
        # Scores below the heuristic gate; only an LLM accept would have stored it.
        RawNewsItem.objects.create(
            source_name="s", url="https://example.com/llm-ok", title="Shipping firm reroutes vessels",
            cleaned_text="Shipping firm reroutes vessels.", published_at=published,
        )
        service = AgentService(config=config)
        try:
            records = service._load_raw_records(published - timedelta(minutes=1), timezone.now())
        finally:
            service.close()
        self.assertEqual([r["url"] for r in records], ["https://example.com/llm-ok"])

    def test_synthetic_urls_are_not_references(self):
        service = AgentService(config=AgentConfig.objects.create())
        try:
            refs = service._normalize_references(["https://synthetic.local/src/1-abc", "https://real.example/a"])
        finally:
            service.close()
        self.assertEqual(refs, ["https://real.example/a"])

    def test_worker_start_fails_runs_orphaned_by_a_restart(self):
        from agent.services import runtime

        AgentConfig.objects.create()
        orphan = AgentRun.objects.create(status=AgentRun.STATUS_RUNNING)
        with mock.patch.object(runtime, "prune_old_data", return_value={}), \
             mock.patch.object(runtime, "close_old_connections"):
            runtime.run_worker(max_iterations=1, sleep=lambda _s: None)
        orphan.refresh_from_db()
        self.assertEqual(orphan.status, AgentRun.STATUS_FAILED)
        self.assertIsNotNone(orphan.ended_at)


class IngestionTests(TestCase):
    def setUp(self):
        from agent.models import NewsSource

        self.config = AgentConfig.objects.create(llm_api_key="k", use_llm_summaries=False, llm_daily_request_budget=100)
        self.source = NewsSource.objects.create(name="Wire", base_url="https://wire.example/rss", source_type="rss")
        self.service = AgentService(config=self.config)
        self.published = timezone.now() - timedelta(minutes=5)

    def tearDown(self):
        self.service.close()

    def _item(self, slug, title, text):
        return {"title": title, "summary": text, "content": text, "url": f"https://wire.example/{slug}", "published_at": self.published}

    def test_feed_parser_reads_rdf_and_atom(self):
        from agent.services.fetching import parse_feed

        rdf = """<?xml version="1.0"?>
        <rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#" xmlns="http://purl.org/rss/1.0/"
                 xmlns:dc="http://purl.org/dc/elements/1.1/">
          <item rdf:about="https://boj.example/a"><title>BoJ statement</title>
            <link>https://boj.example/a</link><dc:date>2026-10-21T09:00:00+09:00</dc:date></item>
        </rdf:RDF>"""
        atom = """<feed xmlns="http://www.w3.org/2005/Atom"><entry><title>ECB speech</title>
            <link rel="enclosure" href="https://ecb.example/a.pdf"/><link href="https://ecb.example/a"/>
            <updated>2026-10-21T10:00:00Z</updated><summary>Rates</summary></entry></feed>"""
        self.assertEqual(
            [(i["title"], i["url"], i["published"]) for i in parse_feed(rdf) + parse_feed(atom)],
            [("BoJ statement", "https://boj.example/a", "2026-10-21T09:00:00+09:00"),
             ("ECB speech", "https://ecb.example/a", "2026-10-21T10:00:00Z")],
        )

    def test_llm_batch_filter_decides_and_heuristic_covers_the_rest(self):
        from agent.services.base import SourceFetchResult
        from dataset.models import RawNewsItem

        items = [
            self._item("rejected", "Fed raises interest rates", RELEVANT_TEXT),
            self._item("rescued", "Shipping firm reroutes vessels around canal", "Shipping firm reroutes vessels."),
            self._item("undecided", "ECB inflation decision moves bond yields", RELEVANT_TEXT),
            self._item("junk", "Celebrity wedding album", "A celebrity wedding."),
        ]
        reply = {"decisions": [{"id": 1, "decision": "reject"}, {"id": 2, "decision": "accept"}]}
        run = AgentRun.objects.create()
        with mock.patch.object(self.service, "_fetch_source_batch", return_value=SourceFetchResult(self.source.id, items, 5)), \
             mock.patch.object(self.service, "_relevance_score", side_effect=lambda text, title: 2 if "Shipping" in title else (-5 if "Celebrity" in title else 10)), \
             mock.patch.object(self.service, "_enrich_full_text", return_value=0), \
             mock.patch.object(self.service.llm, "generate_json", return_value=reply) as llm:
            stats = self.service._fetch_and_store_sources(run)
        self.assertEqual(llm.call_count, 1)  # one request for the whole batch
        prompt = llm.call_args[0][0]
        self.assertIn("[1] (Wire) Fed raises", prompt)
        self.assertNotIn("Celebrity", prompt)  # below the review floor: never sent
        stored = set(RawNewsItem.objects.values_list("url", flat=True))
        self.assertEqual(stored, {"https://wire.example/rescued", "https://wire.example/undecided"})
        self.assertEqual((stats.items_seen, stats.items_saved, stats.items_rejected), (4, 2, 2))

    def test_filter_leaves_a_share_of_the_daily_budget_to_articles(self):
        self.assertEqual(self.service.llm_reserved_for_articles, 30)
        self.service.llm_requests_used = 70
        self.assertFalse(self.service._llm_filter_available(AgentRun.objects.create()))

    def test_failing_source_backs_off_longer_each_time(self):
        self.service._record_source_error(self.source, "http_500")
        first = self.source.backoff_until
        self.service._record_source_error(self.source, "http_500")
        self.assertGreater(self.source.backoff_until - first, timedelta(minutes=10))

    def test_article_text_is_extracted_from_paragraphs(self):
        from agent.services.fetching import extract_article_text

        para = "The central bank held rates steady while signalling that inflation risks remain elevated. " * 2
        html = f"<html><nav><p>{'menu ' * 30}</p></nav><article><p>{para}</p><p>{para}</p><p>{para}</p></article></html>"
        text = extract_article_text(html)
        self.assertIn("central bank held rates", text)
        self.assertNotIn("menu", text)
        self.assertEqual(extract_article_text("<p>short</p>"), "")


class ArticleCompositionTests(TestCase):
    def setUp(self):
        from articles.models import AssetCandle, AssetSeries

        self.config = AgentConfig.objects.create(use_llm_summaries=False)
        self.service = AgentService(config=self.config)
        self.day = (timezone.now() - timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
        PriceSource.objects.create(name="g", symbol="XAU", chart_label="Gold")
        series = AssetSeries.objects.create(symbol="XAU", label="Gold")
        for minutes, price in ((60, 2400.0), (600, 2430.0)):
            AssetCandle.objects.create(
                series=series, timestamp=self.day + timedelta(minutes=minutes), open=price, high=price + 5, low=price - 5, close=price
            )

    def tearDown(self):
        self.service.close()

    def test_paragraph_breaks_survive_cleanup(self):
        text = self.service._strip_time_window_phrasing("Lead  paragraph.\n\n## Markets\n- Gold rose.")
        self.assertEqual(text, "Lead paragraph.\n\n## Markets\n- Gold rose.")

    def test_day_context_has_child_briefs_and_price_data(self):
        from articles.models import Card, CardArticle

        block = Card.objects.create(
            timeframe=Card.TIMEFRAME_INTRADAY, period_start=self.day + timedelta(hours=8),
            period_end=self.day + timedelta(hours=12), status=Card.STATUS_FINAL, slug="b",
        )
        CardArticle.objects.create(card=block, kind="main", uuid=block.uuid, title="Gold climbs on Fed bets", summary="S", body="B")
        from articles.services import describe_price_moves, tracked_series

        price_moves = describe_price_moves(tracked_series(), self.day, self.day + timedelta(days=1))
        self.assertIn("Gold: opened at 2,400.00, last 2,430.00 (+1.25%)", price_moves)
        context = self.service._build_context_from_records(
            [], timeframe=Card.TIMEFRAME_DAY, period_start=self.day, period_end=self.day + timedelta(days=1), price_moves=price_moves
        )
        self.assertIn("Gold climbs on Fed bets", context)
        self.assertIn("+1.25%", context)

    def test_prompt_asks_for_the_timeframe_format(self):
        prompt = self.service._build_article_prompt("ctx", "day", self.day, self.day)
        self.assertIn("600-900 words", prompt)
        self.assertIn("ctx", prompt)

    def test_fallback_body_lists_market_moves(self):
        payload = self.service._compose_fallback_payload([], "day", self.day, self.day, price_moves="Gold: up")
        self.assertIn("## Market moves\n- Gold: up", payload["body"])


class PriceProviderTests(TestCase):
    def setUp(self):
        price_sync._ccxt_paused_until = 0.0
        price_sync._yf_synced_at = None
        price_sync._yf_covered.clear()

    def test_closed_market_history_is_not_refetched_every_sync(self):
        import pandas as pd

        from articles.models import AssetCandle, AssetSeries

        spx = AssetSeries.objects.create(symbol="^GSPC")
        now = timezone.now()
        friday_close = now - timedelta(days=2)
        AssetCandle.objects.create(series=spx, timestamp=friday_close, open=1, high=1, low=1, close=1)
        fake_yf = mock.Mock(download=mock.Mock(return_value=pd.DataFrame()))
        with mock.patch.dict("sys.modules", {"yfinance": fake_yf}):
            price_sync._sync_from_yfinance(price_sync.PriceFeedStats(), now)
            price_sync._sync_from_yfinance(price_sync.PriceFeedStats(), now + timedelta(seconds=15))
        first, second = (c.kwargs["start"] for c in fake_yf.download.call_args_list)
        self.assertLess(first, friday_close)
        self.assertGreater(second, now - timedelta(minutes=15))

    def test_yfinance_writes_new_bars_in_one_batch_request(self):
        import pandas as pd

        from articles.models import AssetCandle, AssetSeries

        gold = AssetSeries.objects.create(symbol="XAUUSD=X")
        now = timezone.now().replace(second=0, microsecond=0)
        AssetCandle.objects.create(series=gold, timestamp=now - timedelta(minutes=2), open=1, high=1, low=1, close=1)
        index = pd.DatetimeIndex([now - timedelta(minutes=m) for m in (3, 2, 1)])
        frame = pd.DataFrame(
            {"Open": [9, 10, 11], "High": [9, 12, 13], "Low": [9, 9, 10], "Close": [9, 11, 12], "Volume": [0, 5, 6]}, index=index
        )
        data = pd.concat({"GC=F": frame}, axis=1)
        fake_yf = mock.Mock(download=mock.Mock(return_value=data))
        with mock.patch.dict("sys.modules", {"yfinance": fake_yf}):
            served = price_sync._sync_from_yfinance(price_sync.PriceFeedStats(), timezone.now())
        self.assertEqual(served, {"XAUUSD=X"})
        fake_yf.download.assert_called_once()
        closes = list(AssetCandle.objects.filter(series=gold).order_by("timestamp").values_list("close", flat=True))
        self.assertEqual(closes, [11.0, 12.0])  # the older bar before the last stored one is skipped

    def test_price_sources_skip_symbols_the_providers_served(self):
        PriceSource.objects.create(name="cg", symbol="BTC-USD", source_type=PriceSource.SOURCE_API, base_url="https://cg.example/p")
        stats = price_sync.PriceFeedStats()
        with mock.patch.object(price_sync, "_fetch_api_items") as fetch:
            price_sync._sync_from_price_sources(stats, timezone.now(), skip_symbols={"BTC-USD"})
        fetch.assert_not_called()

    def test_crypto_falls_back_to_yahoo_when_the_exchange_fails(self):
        from articles.models import AssetSeries

        AssetSeries.objects.create(symbol="BTC-USD")
        with mock.patch.object(price_sync, "_sync_from_ccxt", return_value=set()), \
             mock.patch.object(price_sync, "_sync_from_yfinance", return_value=set()) as yf:
            price_sync.sync_price_feeds()
        self.assertEqual(yf.call_args.kwargs["extra"], {"BTC-USD": "BTC-USD"})

    def test_env_api_key_is_used_and_enables_seeded_source(self):
        from agent.models import NewsSource

        with mock.patch.dict("os.environ", {"FINNHUB_API_KEY": "secret"}):
            call_command("seed_sources", verbosity=0)
            finnhub = NewsSource.objects.get(base_url="https://finnhub.io/api/v1/news")
            self.assertEqual(finnhub.resolved_api_key, "secret")
        self.assertTrue(finnhub.enabled)
        self.assertFalse(NewsSource.objects.get(base_url="https://newsapi.org/v2/everything").enabled)


class FetchSafetyTests(TestCase):
    def test_full_text_fetch_only_targets_public_hosts(self):
        from agent.services.fetching import is_public_http_url

        with mock.patch("socket.getaddrinfo", return_value=[(2, 1, 6, "", ("10.0.0.5", 80))]):
            self.assertFalse(is_public_http_url("http://db.internal/x"))
        with mock.patch("socket.getaddrinfo", return_value=[(2, 1, 6, "", ("93.184.216.34", 443))]):
            self.assertTrue(is_public_http_url("https://news.example/a"))
        self.assertFalse(is_public_http_url("file:///etc/passwd"))
        with mock.patch("socket.getaddrinfo", return_value=[(2, 1, 6, "", ("198.18.0.7", 443))]), \
             mock.patch("agent.services.fetching._ALLOW_FAKE_IP", False):
            self.assertFalse(is_public_http_url("https://news.example/a"))  # fake-IP range: opt-in only

    def test_full_text_fetch_connects_to_the_checked_address(self):
        from agent.services.fetching import resolve_public_url

        with mock.patch("socket.getaddrinfo", return_value=[(2, 1, 6, "", ("93.184.216.34", 443))]):
            self.assertEqual(
                resolve_public_url("https://news.example/a?b=1"),
                ("https://93.184.216.34/a?b=1", "news.example", "news.example"),
            )
        with mock.patch("socket.getaddrinfo", return_value=[(10, 1, 6, "", ("2606:2800::1", 8080, 0, 0))]):
            self.assertEqual(
                resolve_public_url("http://news.example:8080/a"),
                ("http://[2606:2800::1]:8080/a", "news.example:8080", "news.example"),
            )
        # One internal answer among public ones rejects the name.
        with mock.patch("socket.getaddrinfo", return_value=[(2, 1, 6, "", ("93.184.216.34", 443)), (2, 1, 6, "", ("127.0.0.1", 443))]):
            self.assertIsNone(resolve_public_url("https://news.example/a"))

    def test_llm_rejected_item_is_not_reviewed_again(self):
        from agent.models import NewsSource
        from agent.services import fetching
        from agent.services.base import SourceFetchResult

        config = AgentConfig.objects.create(llm_api_key="k", use_llm_summaries=False)
        source = NewsSource.objects.create(name="W", base_url="https://w.example/rss", source_type="rss")
        item = {"title": "Fed raises interest rates", "summary": RELEVANT_TEXT, "content": RELEVANT_TEXT,
                "url": "https://w.example/rejected-once", "published_at": timezone.now() - timedelta(minutes=5)}
        service = AgentService(config=config)
        reply = {"decisions": [{"id": 1, "decision": "reject"}]}
        try:
            with mock.patch.object(service, "_fetch_source_batch", return_value=SourceFetchResult(source.id, [item], 1)), \
                 mock.patch.object(service.llm, "generate_json", return_value=reply) as llm:
                service._fetch_and_store_sources(AgentRun.objects.create())
                service._fetch_and_store_sources(AgentRun.objects.create())
        finally:
            service.close()
            fetching._llm_rejected_urls.clear()
        self.assertEqual(llm.call_count, 1)


class WorkerLockTests(TestCase):
    def test_second_worker_waits_while_the_lock_is_held(self):
        import psycopg

        from agent.models import AgentLogEvent
        from agent.services import runtime
        from core.db import db_connect_params

        AgentConfig.objects.create()
        holder = psycopg.connect(**db_connect_params(), autocommit=True)
        holder.execute("SELECT pg_advisory_lock(%s)", [runtime.WORKER_LOCK_ID])
        waits = []

        def sleep(seconds):
            waits.append(seconds)
            holder.close()  # the active worker goes away

        try:
            with mock.patch.object(runtime, "prune_old_data", return_value={}), \
                 mock.patch.object(runtime, "close_old_connections"):
                runtime.run_worker(max_iterations=1, sleep=sleep)
        finally:
            holder.close()
        self.assertEqual(waits[0], runtime.WORKER_LOCK_RETRY_SECONDS)
        self.assertTrue(AgentLogEvent.objects.filter(message="worker_standby_another_worker_active").exists())
