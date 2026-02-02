from datetime import timedelta

from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from articles.models import Article, HourlyBrief


TEST_DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": ":memory:",
    }
}


@override_settings(DATABASES=TEST_DATABASES)
class ArticleApiTests(TestCase):
    def setUp(self):
        self.client = APIClient()

    def test_health_ok(self):
        resp = self.client.get("/api/health/")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), {"status": "ok"})

    def test_article_ingest_creates_and_updates(self):
        now = timezone.now()
        payload = {
            "url": "https://example.com/a",
            "source": "example.com",
            "published_at": now.isoformat(),
            "fetched_at": now.isoformat(),
            "title": "First",
            "body": "Body text",
            "language": "en",
        }
        resp = self.client.post("/api/articles/ingest/", payload, format="json")
        self.assertEqual(resp.status_code, 201)
        self.assertTrue(resp.json()["created"])

        payload["title"] = "Updated title"
        resp = self.client.post("/api/articles/ingest/", payload, format="json")
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(resp.json()["created"])

    def test_article_summary_limits_results(self):
        now = timezone.now()
        for idx in range(3):
            Article.objects.create(
                url=f"https://example.com/{idx}",
                source="example.com",
                published_at=now - timedelta(minutes=idx),
                fetched_at=now,
                title=f"Story {idx}",
                body="Some body text",
            )

        resp = self.client.get("/api/articles/summary/?limit=1")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["count"], 1)
        self.assertIn("brief_slug", data)
        self.assertIn("brief_title", data)
        self.assertIn("summary", data)

    def test_brief_current_and_headlines(self):
        now = timezone.now()
        HourlyBrief.objects.create(
            hour_start=now - timedelta(hours=2),
            hour_end=now - timedelta(hours=1),
            slug="2024-01-01-10",
            title="Earlier brief",
            summary="Earlier summary",
            references=["https://example.com/older"],
            article_count=0,
        )
        HourlyBrief.objects.create(
            hour_start=now - timedelta(hours=1),
            hour_end=now,
            slug="2024-01-01-11",
            title="Latest brief",
            summary="Latest summary",
            references=["https://example.com/latest"],
            article_count=1,
        )

        current = self.client.get("/api/briefs/current/")
        self.assertEqual(current.status_code, 200)
        self.assertIn("slug", current.json())

        headlines = self.client.get("/api/briefs/headlines/?limit=1")
        self.assertEqual(headlines.status_code, 200)
        self.assertEqual(len(headlines.json()["results"]), 1)
