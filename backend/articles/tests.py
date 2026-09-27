import json
from datetime import timedelta

from django.db import IntegrityError
from django.test import TestCase, TransactionTestCase
from django.urls import Resolver404, resolve
from django.utils import timezone

from agent.control_auth import issue_control_token
from agent.models import AgentConfig
from articles.models import AssetCandle, AssetSeries, Card, CardArticle


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

    def test_briefs_interleave_timeframes_by_recency(self):
        day_start = (timezone.now() - timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
        _card(Card.TIMEFRAME_HOUR, day_start + timedelta(hours=5), day_start + timedelta(hours=6), "older-hour")
        _card(Card.TIMEFRAME_DAY, day_start, day_start + timedelta(days=1), "the-day")
        titles = [r["title"] for r in self.client.get("/api/briefs/").json()["results"]]
        self.assertEqual(titles, ["the-day", "older-hour"])


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
            timeframe=Card.TIMEFRAME_HOUR, period_start=now, period_end=now + timedelta(hours=1),
            status=Card.STATUS_FINAL, slug="c",
        )
        article = await CardArticle.objects.acreate(card=card, kind=CardArticle.KIND_MAIN, uuid=card.uuid, title="Hello")
        chunk = await self._first_event(f"/api/stream/articles/{article.slug}/")
        lines = chunk.strip().split("\n")
        self.assertEqual(lines[0], "event: article")
        self.assertEqual(json.loads(lines[1].removeprefix("data: "))["title"], "Hello")

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
