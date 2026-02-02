from datetime import timedelta
from unittest.mock import patch

from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from articles.models import Article
from crawler.models import CrawlLogEvent, CrawlRun


TEST_DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": ":memory:",
    }
}


@override_settings(DATABASES=TEST_DATABASES)
class CrawlerApiTests(TestCase):
    def setUp(self):
        self.client = APIClient()

    def test_crawler_status_empty(self):
        resp = self.client.get("/api/crawler/status/")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertFalse(data["running"])
        self.assertIsNone(data["last_run"])

    def test_crawler_run_starts_and_rejects(self):
        with patch("crawler.views.start_crawler_async", return_value=True):
            resp = self.client.post("/api/crawler/run/")
            self.assertEqual(resp.status_code, 202)
            self.assertEqual(resp.json()["status"], "started")

        with patch("crawler.views.start_crawler_async", return_value=False):
            resp = self.client.post("/api/crawler/run/")
            self.assertEqual(resp.status_code, 409)
            self.assertEqual(resp.json()["status"], "already_running")

    def test_crawler_config_get_and_update(self):
        resp = self.client.get("/api/crawler/config/")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("llm_enabled", resp.json())

        resp = self.client.put(
            "/api/crawler/config/",
            {"llm_enabled": False, "max_pages_per_run": 5},
            format="json",
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertFalse(data["llm_enabled"])
        self.assertEqual(data["max_pages_per_run"], 5)

    def test_crawler_seeds_list_and_create(self):
        resp = self.client.get("/api/crawler/seeds/")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), [])

        resp = self.client.post(
            "/api/crawler/seeds/",
            {"url": "https://example.com"},
            format="json",
        )
        self.assertEqual(resp.status_code, 201)
        self.assertEqual(resp.json()["url"], "https://example.com")

        resp = self.client.get("/api/crawler/seeds/")
        self.assertEqual(len(resp.json()), 1)

    def test_crawler_logs_limit(self):
        run = CrawlRun.objects.create(status=CrawlRun.STATUS_DONE)
        CrawlLogEvent.objects.create(
            run=run,
            step=CrawlLogEvent.STEP_FETCH_RESPONSE,
            level=CrawlLogEvent.LEVEL_INFO,
            message="Fetched",
            content="ok",
        )
        resp = self.client.get("/api/crawler/logs/?limit=1")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.json()["results"]), 1)

    def test_crawler_export_csv(self):
        now = timezone.now()
        Article.objects.create(
            url="https://example.com/article",
            source="example.com",
            published_at=now - timedelta(minutes=5),
            fetched_at=now,
            title="Example",
            body="Body text " * 20,
        )
        resp = self.client.get("/api/crawler/export.csv")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp["X-Exported-Rows"], "1")
        self.assertIn("published_at,fetched_at,source,url,title,body,language", resp.content.decode())
