from __future__ import annotations

from django.db import models

from core.models import TimeStampedModel

DEFAULT_PROMPT = (
    "You are a high-precision news extraction and URL selection system.\n"
    "Task: From the combined context of multiple seed pages, extract news items and select the best next URLs.\n"
    "Seed/Current URLs:\n"
    "{seed_urls}\n\n"
    "Context (cleaned text from all pages):\n"
    "{context}\n\n"
    "Candidate URLs by seed:\n"
    "{candidate_urls}\n\n"
    "Return ONLY valid JSON with this schema:\n"
    "{{\n"
    '  "next_urls_by_seed": [\n'
    "    {{\n"
    '      "seed_url": "https://seed.example",\n'
    '      "next_url": "https://next.example"\n'
    "    }}\n"
    "  ],\n"
    '  "articles": [\n'
    "    {{\n"
    '      "url": "https://...",\n'
    '      "title": "...",\n'
    '      "published_at": "ISO-8601 timestamp if present",\n'
    '      "source": "example.com",\n'
    '      "body": "full article text from the context"\n'
    "    }}\n"
    "  ]\n"
    "}}\n\n"
    "Rules:\n"
    "- Choose one next_url per seed_url when possible.\n"
    "- Extract up to {max_articles} articles.\n"
    "- Keep each body under ~{max_article_chars} characters.\n"
    "- Only include real news articles with clean, readable sentences.\n"
    "- Exclude error pages, redirects, login pages, and boilerplate.\n"
    "- Never include text like HTTP status codes, \"Moved Permanently\", or server banners.\n"
    "- If a page has no valid article, do not include it in articles.\n"
    "- Do not invent facts, URLs, or timestamps.\n"
)

DEFAULT_BRIEF_PROMPT = (
    "You are a senior news editor writing an hourly market-moving brief.\n"
    "Goal: Summarize the most important developments with potential impact on global financial markets.\n"
    "Context: recent articles from the last hour.\n\n"
    "Articles:\n"
    "{articles}\n\n"
    "Return ONLY valid JSON with this schema:\n"
    "{{\n"
    '  "title": "Short headline for the hour",\n'
    '  "summary": "One concise paragraph (3-5 sentences)",\n'
    '  "references": ["https://source.url/1", "https://source.url/2"]\n'
    "}}\n\n"
    "Rules:\n"
    "- Focus on facts present in the provided articles only.\n"
    "- Prefer clarity over hype; keep it professional.\n"
    "- Keep the summary under 1200 characters.\n"
    "- Use at most 5 reference URLs.\n"
)


class CrawlerConfig(TimeStampedModel):
    llm_enabled = models.BooleanField(default=True)
    llm_provider = models.CharField(max_length=32, default="openai")
    llm_model = models.CharField(max_length=128, default="gpt-4o-mini")
    llm_base_url = models.URLField(blank=True, default="")
    llm_api_key = models.CharField(max_length=255, blank=True, default="")
    llm_temperature = models.FloatField(default=0.1)
    llm_max_output_tokens = models.PositiveIntegerField(default=1400)
    brief_temperature = models.FloatField(default=0.2)
    brief_max_output_tokens = models.PositiveIntegerField(default=600)

    max_context_chars = models.PositiveIntegerField(default=12000)
    max_next_urls = models.PositiveIntegerField(default=10)
    max_articles = models.PositiveIntegerField(default=20)
    max_article_chars = models.PositiveIntegerField(default=2000)
    max_pages_per_run = models.PositiveIntegerField(default=50)
    max_depth = models.PositiveIntegerField(default=3)
    brief_max_articles = models.PositiveIntegerField(default=20)
    brief_max_context_chars = models.PositiveIntegerField(default=12000)

    request_delay_seconds = models.FloatField(default=1.0)
    user_agent = models.CharField(max_length=255, default="nousnews-crawler/1.0 (+https://crawler.miyangroup.com)")
    allow_external_domains = models.BooleanField(default=False)

    prompt_template = models.TextField(default=DEFAULT_PROMPT)
    brief_prompt_template = models.TextField(default=DEFAULT_BRIEF_PROMPT)

    class Meta:
        verbose_name = "Crawler Configuration"
        verbose_name_plural = "Crawler Configuration"


class CrawlSeed(TimeStampedModel):
    url = models.URLField(max_length=1000, unique=True)
    config = models.ForeignKey(
        CrawlerConfig,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="seeds",
    )
    is_active = models.BooleanField(default=True)
    last_fetched_at = models.DateTimeField(null=True, blank=True)
    last_error = models.TextField(blank=True, default="")

    def __str__(self) -> str:
        return self.url


class CrawlQueueItem(TimeStampedModel):
    STATUS_PENDING = "pending"
    STATUS_IN_PROGRESS = "in_progress"
    STATUS_DONE = "done"
    STATUS_FAILED = "failed"

    STATUS_CHOICES = [
        (STATUS_PENDING, "Pending"),
        (STATUS_IN_PROGRESS, "In progress"),
        (STATUS_DONE, "Done"),
        (STATUS_FAILED, "Failed"),
    ]

    url = models.URLField(max_length=1000, unique=True)
    seed = models.ForeignKey(CrawlSeed, null=True, blank=True, on_delete=models.SET_NULL)
    seed_url = models.URLField(max_length=1000, blank=True, default="")
    depth = models.PositiveIntegerField(default=0)

    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_PENDING)
    discovered_at = models.DateTimeField(auto_now_add=True)
    last_attempt_at = models.DateTimeField(null=True, blank=True)
    attempts = models.PositiveIntegerField(default=0)
    last_error = models.TextField(blank=True, default="")

    class Meta:
        indexes = [
            models.Index(fields=["status", "discovered_at"]),
            models.Index(fields=["seed_url", "status"]),
        ]

    def __str__(self) -> str:
        return f"{self.url} ({self.status})"


class CrawlRun(TimeStampedModel):
    STATUS_RUNNING = "running"
    STATUS_DONE = "done"
    STATUS_FAILED = "failed"

    status = models.CharField(max_length=20, default=STATUS_RUNNING)
    objective = models.TextField(blank=True, default="")
    use_llm_filtering = models.BooleanField(default=True)
    started_at = models.DateTimeField(auto_now_add=True)
    ended_at = models.DateTimeField(null=True, blank=True)
    pages_processed = models.PositiveIntegerField(default=0)
    articles_created = models.PositiveIntegerField(default=0)
    queued_urls = models.PositiveIntegerField(default=0)
    last_error = models.TextField(blank=True, default="")

    class Meta:
        ordering = ["-started_at"]


class CrawlLogEvent(TimeStampedModel):
    LEVEL_INFO = "info"
    LEVEL_WARN = "warn"
    LEVEL_ERROR = "error"

    STEP_FETCH_RESPONSE = "fetch_response"
    STEP_CLEANED_TEXT = "cleaned_text"
    STEP_LLM_PROMPT = "llm_prompt"
    STEP_LLM_OUTPUT = "llm_output"
    STEP_NEXT_STEP = "next_step"
    STEP_ERROR = "error"

    LEVEL_CHOICES = [
        (LEVEL_INFO, "Info"),
        (LEVEL_WARN, "Warn"),
        (LEVEL_ERROR, "Error"),
    ]

    STEP_CHOICES = [
        (STEP_FETCH_RESPONSE, "Fetch response"),
        (STEP_CLEANED_TEXT, "Cleaned text"),
        (STEP_LLM_PROMPT, "LLM prompt"),
        (STEP_LLM_OUTPUT, "LLM output"),
        (STEP_NEXT_STEP, "Next step"),
        (STEP_ERROR, "Error"),
    ]

    run = models.ForeignKey(CrawlRun, null=True, blank=True, on_delete=models.SET_NULL, related_name="logs")
    queue_item = models.ForeignKey(
        CrawlQueueItem,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="logs",
    )
    seed_url = models.URLField(max_length=1000, blank=True, default="")
    url = models.URLField(max_length=1000, blank=True, default="")
    step = models.CharField(max_length=64, choices=STEP_CHOICES, default=STEP_FETCH_RESPONSE)
    level = models.CharField(max_length=16, choices=LEVEL_CHOICES, default=LEVEL_INFO)
    message = models.CharField(max_length=255, blank=True, default="")
    content = models.TextField(blank=True, default="")
    metadata = models.JSONField(blank=True, default=dict)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["step", "created_at"]),
            models.Index(fields=["run", "created_at"]),
        ]

    def __str__(self) -> str:
        return f"{self.step} ({self.level})"
