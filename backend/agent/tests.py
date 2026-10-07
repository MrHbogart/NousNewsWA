from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from agent.models import AgentConfig
from agent.services import AgentService
from articles.models import AssetSeries, AssetCandle, Card, CardArticle, CardAsset


def _make_final_card(*, importance_score, period_end):
    period_start = period_end - timedelta(hours=1)
    card = Card.objects.create(
        timeframe=Card.TIMEFRAME_INTRADAY,
        period_start=period_start,
        period_end=period_end,
        status=Card.STATUS_FINAL,
        slug=f"hour-{period_start.strftime('%Y%m%d%H%M')}",
        importance_score=importance_score,
    )
    CardArticle.objects.create(
        card=card,
        kind=CardArticle.KIND_MAIN,
        uuid=card.uuid,
        title="Test brief",
        summary="Test summary",
        body="Test body",
    )
    return card


def _attach_price_data(card, *, symbol="XAU"):
    series, _ = AssetSeries.objects.get_or_create(symbol=symbol, defaults={"label": symbol})
    CardAsset.objects.create(card=card, series=series, label=symbol)
    AssetCandle.objects.create(
        series=series, timestamp=card.period_end + timedelta(minutes=1),
        open=100.0, high=101.0, low=99.0, close=100.5,
    )
    AssetCandle.objects.create(
        series=series, timestamp=card.period_end + timedelta(minutes=30),
        open=100.5, high=102.0, low=100.0, close=101.5,
    )


class AftermathArticleTests(TestCase):
    def setUp(self):
        self.config = AgentConfig.objects.create(
            use_llm_summaries=False,
            aftermath_min_importance_score=2,
            aftermath_delay_hour_minutes=60,
        )
        self.now = timezone.now()

    def _run(self):
        service = AgentService(config=self.config)
        try:
            return service._finalize_due_aftermath_cards(run=None, now=self.now)
        finally:
            service.close()

    def test_creates_aftermath_for_eligible_card_with_price_data(self):
        card = _make_final_card(importance_score=2, period_end=self.now - timedelta(minutes=90))
        _attach_price_data(card)

        created = self._run()

        self.assertEqual(created, 1)
        aftermath = card.articles.get(kind=CardArticle.KIND_AFTERMATH)
        self.assertIn("101.50", aftermath.body)
        self.assertIsNotNone(aftermath.aftermath_price_until)

    def test_skips_low_importance_card(self):
        card = _make_final_card(importance_score=1, period_end=self.now - timedelta(minutes=90))
        _attach_price_data(card)

        created = self._run()

        self.assertEqual(created, 0)
        self.assertFalse(card.articles.filter(kind=CardArticle.KIND_AFTERMATH).exists())

    def test_skips_card_not_yet_past_delay(self):
        card = _make_final_card(importance_score=2, period_end=self.now - timedelta(minutes=10))
        _attach_price_data(card)

        created = self._run()

        self.assertEqual(created, 0)

    def test_skips_card_with_no_price_data_yet(self):
        _make_final_card(importance_score=2, period_end=self.now - timedelta(minutes=90))

        created = self._run()

        self.assertEqual(created, 0)

    def test_does_not_duplicate_on_second_run(self):
        card = _make_final_card(importance_score=2, period_end=self.now - timedelta(minutes=90))
        _attach_price_data(card)

        first = self._run()
        second = self._run()

        self.assertEqual(first, 1)
        self.assertEqual(second, 0)
        self.assertEqual(card.articles.filter(kind=CardArticle.KIND_AFTERMATH).count(), 1)
