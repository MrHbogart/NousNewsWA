import json
from datetime import timedelta

from django.db import IntegrityError
from django.test import TestCase, TransactionTestCase
from django.urls import Resolver404, resolve
from django.utils import timezone

from agent.control_auth import issue_control_token
from agent.models import AgentConfig
from articles.models import AssetCandle, AssetSeries, Card, CardArticle, CardAsset


def _card(timeframe, period_start, period_end, slug):
    card = Card.objects.create(
        timeframe=timeframe, period_start=period_start, period_end=period_end,
        status=Card.STATUS_FINAL, slug=slug,
    )
    CardArticle.objects.create(card=card, kind=CardArticle.KIND_MAIN, uuid=card.uuid, title=slug)
    return card


class PublicApiTests(TestCase):
    def test_cards_app_routes_are_gone(self):
        with self.assertRaises(Resolver404):
            resolve("/api/cards/cards/")

    def test_prices_latest_reads_asset_candles(self):
        series = AssetSeries.objects.create(symbol="BTC-USD", label="Bitcoin")
        now = timezone.now().replace(second=0, microsecond=0)
        for minutes, close in ((2, 10.0), (1, 11.0)):
            AssetCandle.objects.create(
                series=series, timestamp=now - timedelta(minutes=minutes),
                open=close, high=close, low=close, close=close,
            )
        body = self.client.get("/api/prices/series/BTC-USD/latest/").json()
        self.assertEqual(body["latest"]["close"], 11.0)

    def test_asset_candle_is_unique_per_series_minute(self):
        series = AssetSeries.objects.create(symbol="X")
        ts = timezone.now()
        AssetCandle.objects.create(series=series, timestamp=ts, open=1, high=1, low=1, close=1)
        with self.assertRaises(IntegrityError):
            AssetCandle.objects.create(series=series, timestamp=ts, open=1, high=1, low=1, close=1)

    def test_finalized_days_collapse_their_intraday_briefs(self):
        today = timezone.now().replace(hour=0, minute=0, second=0, microsecond=0)
        yesterday = today - timedelta(days=1)
        _card(Card.TIMEFRAME_INTRADAY, yesterday + timedelta(hours=4), yesterday + timedelta(hours=8), "old-block")
        _card(Card.TIMEFRAME_DAY, yesterday, today, "the-day")
        _card(Card.TIMEFRAME_INTRADAY, today, today + timedelta(hours=4), "today-block")
        titles = [r["title"] for r in self.client.get("/api/briefs/").json()["results"]]
        self.assertEqual(titles, ["today-block", "the-day"])

        sitemap = [r["slug"] for r in self.client.get("/api/sitemap/").json()["results"]]
        self.assertNotIn("old-block", " ".join(sitemap))
        self.assertEqual(len(sitemap), 2)

        # The old block's page still works and points at its day article.
        old = CardArticle.objects.get(title="old-block")
        body = self.client.get(f"/api/articles/{old.slug}/").json()
        self.assertEqual(body["day_article"]["title"], "the-day")

    def test_intraday_brief_stays_until_its_day_is_finalized(self):
        yesterday = timezone.now().replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=1)
        _card(Card.TIMEFRAME_INTRADAY, yesterday + timedelta(hours=20), yesterday + timedelta(hours=24), "late-block")
        titles = [r["title"] for r in self.client.get("/api/briefs/").json()["results"]]
        self.assertEqual(titles, ["late-block"])

    def test_intraday_window_is_a_4_hour_block(self):
        from articles.services import get_period_window

        at = timezone.now().replace(hour=13, minute=37)
        start, end = get_period_window(at, Card.TIMEFRAME_INTRADAY)
        self.assertEqual((start.hour, start.minute, end - start), (12, 0, timedelta(hours=4)))


class AgentConfigApiTests(TestCase):
    def setUp(self):
        from django.contrib.auth.hashers import make_password

        AgentConfig.objects.create(control_password_hash=make_password("a-long-password"))
        token, _ = issue_control_token()
        self.auth = {"HTTP_AUTHORIZATION": f"Bearer {token}"}

    def test_config_exposes_aftermath_fields_and_protects_base_url(self):
        body = self.client.get("/api/agent/config/", **self.auth).json()
        self.assertIn("aftermath_min_importance_score", body)
        self.assertIn("aftermath_prompt_template", body)

        resp = self.client.put(
            "/api/agent/config/",
            data={"llm_base_url": "https://evil.example/v1", "aftermath_min_importance_score": 3},
            content_type="application/json",
            **self.auth,
        )
        self.assertEqual(resp.status_code, 200)
        config = AgentConfig.objects.get()
        self.assertEqual(config.llm_base_url, "")
        self.assertEqual(config.aftermath_min_importance_score, 3)


class StreamTests(TransactionTestCase):
    def test_sse_event_format(self):
        from articles.stream import sse_event

        self.assertEqual(sse_event("x", {"a": 1}), 'event: x\ndata: {"a": 1}\n\n')

    async def _first_event(self, url):
        response = await self.async_client.get(url)
        self.assertEqual(response["Content-Type"], "text/event-stream")
        self.assertEqual(response["Cache-Control"], "no-cache")
        stream = aiter(response.streaming_content)
        try:
            chunk = await anext(stream)
        finally:
            await stream.aclose()
        return chunk.decode() if isinstance(chunk, bytes) else chunk

    async def test_home_stream_starts_with_current_data(self):
        chunk = await self._first_event("/api/stream/home/")
        lines = chunk.strip().split("\n")
        self.assertEqual(lines[0], "event: home")
        payload = json.loads(lines[1].removeprefix("data: "))
        self.assertIn("lasthour", payload)
        self.assertIn("results", payload["briefs"])

    async def test_article_stream_sends_article(self):
        now = timezone.now()
        card = await Card.objects.acreate(
            timeframe=Card.TIMEFRAME_INTRADAY, period_start=now, period_end=now + timedelta(hours=1),
            status=Card.STATUS_FINAL, slug="c",
        )
        article = await CardArticle.objects.acreate(card=card, kind=CardArticle.KIND_MAIN, uuid=card.uuid, title="Hello")
        chunk = await self._first_event(f"/api/stream/articles/{article.slug}/")
        lines = chunk.strip().split("\n")
        self.assertEqual(lines[0], "event: article")
        self.assertEqual(json.loads(lines[1].removeprefix("data: "))["title"], "Hello")

    async def _pushed_after(self, url, change, event):
        """Open `url`, apply `change` once the stream is idle; return (seconds, payload) of `event`."""
        import asyncio

        from articles import stream as stream_module

        response = await self.async_client.get(url)
        stream = aiter(response.streaming_content)
        try:
            await anext(stream)  # initial event
            await anext(stream)  # retry hint
            # Keep the stream consuming (as a server would) while the watcher
            # takes its first fingerprints and the LISTEN connection comes up.
            pending = asyncio.ensure_future(anext(stream))
            while None in stream_module.watcher.fingerprints.values():
                await asyncio.sleep(0.05)
            while True:  # drain startup events until the stream is quiet
                try:
                    await asyncio.wait_for(asyncio.shield(pending), 0.5)
                except asyncio.TimeoutError:
                    break
                pending = asyncio.ensure_future(anext(stream))
            await change()
            loop = asyncio.get_running_loop()
            started = loop.time()
            while True:
                chunk = await asyncio.wait_for(pending, 10)
                chunk = chunk.decode() if isinstance(chunk, bytes) else chunk
                if chunk.startswith(f"event: {event}"):
                    return loop.time() - started, json.loads(chunk.split("\n")[1].removeprefix("data: "))
                pending = asyncio.ensure_future(anext(stream))
        finally:
            await stream.aclose()

    async def _open_card(self):
        now = timezone.now()
        card = await Card.objects.acreate(
            timeframe=Card.TIMEFRAME_INTRADAY, period_start=now, period_end=now + timedelta(hours=1),
            status=Card.STATUS_OPEN, slug="c",
        )
        article = await CardArticle.objects.acreate(card=card, kind=CardArticle.KIND_MAIN, uuid=card.uuid, title="Old")
        return card, article

    async def test_article_stream_pushes_changes(self):
        from articles.stream import POLL_SECONDS

        card, article = await self._open_card()

        async def change():
            # Card-only change: invisible to the fingerprint, so only NOTIFY pushes it.
            await Card.objects.filter(pk=card.pk).aupdate(importance_score=7)

        elapsed, payload = await self._pushed_after(f"/api/stream/articles/{article.slug}/", change, "article")
        self.assertLess(elapsed, POLL_SECONDS)
        self.assertEqual(payload["importance_score"], 7)

    async def test_article_stream_pushes_live_prices(self):
        from articles.stream import POLL_SECONDS

        card, article = await self._open_card()
        series = await AssetSeries.objects.acreate(symbol="BTC-USD", label="Bitcoin")  # provider-mapped
        await CardAsset.objects.acreate(card=card, series=series)

        async def change():
            ts = card.period_start + timedelta(minutes=1)
            await AssetCandle.objects.acreate(series=series, timestamp=ts, open=1, high=2, low=1, close=1.5)

        elapsed, payload = await self._pushed_after(f"/api/stream/articles/{article.slug}/", change, "prices")
        self.assertLess(elapsed, POLL_SECONDS)
        self.assertEqual(payload["id"], str(article.uuid))
        self.assertEqual(payload["price_series"][0]["candles"][-1]["close"], 1.5)

    async def test_article_stream_404(self):
        response = await self.async_client.get("/api/stream/articles/nope/")
        self.assertEqual(response.status_code, 404)


class HealthTests(TestCase):
    def test_health_reports_agent_worker_state(self):
        from agent.models import AgentWorker

        AgentConfig.objects.create(run_forever_enabled=True)
        AgentWorker.objects.create(pk=1, heartbeat_at=timezone.now())
        body = self.client.get("/api/health/").json()
        self.assertEqual(body["status"], "ok")
        self.assertTrue(body["agent"]["running"])
        self.assertIn("last_price_sync_at", body["agent"])


class PriceLabelTests(TestCase):
    def test_provider_mapped_series_are_charted_without_a_price_source(self):
        from agent.models import PriceSource
        from articles.services import enabled_price_source_labels

        AssetSeries.objects.create(symbol="^GSPC", label="S&P 500 Index")
        AssetSeries.objects.create(symbol="DGS10", label="10Y (no provider, no source)")
        PriceSource.objects.create(name="CoinGecko", symbol="BTC-USD", chart_label="Bitcoin", source_type="api")
        self.assertEqual(enabled_price_source_labels(), {"^GSPC": "S&P 500 Index", "BTC-USD": "Bitcoin"})
