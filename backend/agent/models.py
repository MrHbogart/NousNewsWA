from __future__ import annotations

import os
from urllib.parse import urlparse

from django.db import models

from core.models import TimeStampedModel

# Provider domain -> environment variable holding its API key. A key set on the
# NewsSource/PriceSource row in admin wins; otherwise the env var is used, so
# keys can live in .env instead of the database.
PROVIDER_KEY_ENV = {
    "finnhub.io": "FINNHUB_API_KEY",
    "alphavantage.co": "ALPHAVANTAGE_API_KEY",
    "newsapi.org": "NEWSAPI_API_KEY",
    "gnews.io": "GNEWS_API_KEY",
    "marketaux.com": "MARKETAUX_API_KEY",
    "stlouisfed.org": "FRED_API_KEY",
    "twelvedata.com": "TWELVEDATA_API_KEY",
}


def provider_key_env(url: str) -> str:
    """Name of the env var holding the API key for this URL's provider, or ""."""
    host = (urlparse(url or "").hostname or "").lower()
    for domain, env_name in PROVIDER_KEY_ENV.items():
        if host == domain or host.endswith("." + domain):
            return env_name
    return ""


class ApiKeyMixin:
    @property
    def requires_api_key(self) -> bool:
        return bool(self.api_key_param or self.api_key_header)

    @property
    def resolved_api_key(self) -> str:
        env_name = provider_key_env(self.base_url)
        return (self.api_key or "").strip() or (os.getenv(env_name, "").strip() if env_name else "")

DEFAULT_ARTICLE_PROMPT = (
    "You are the lead markets editor at NousNews. Write one market article from the source records below for\n"
    "readers who want to know what moved markets and why: professional investors and informed retail readers alike.\n\n"
    "Editorial rules:\n"
    "- Use only facts stated in the source records or the price data. Never invent numbers, quotes, or events.\n"
    "- Cover what matters to markets: central banks and rates, economic data, earnings and deals, commodities,\n"
    "  currencies, crypto, and geopolitics with economic impact. Skip sports, entertainment, and lifestyle stories.\n"
    "- Explain cause and effect plainly: what happened, why it matters, and which markets it touched.\n"
    "- When price data is given, cite the actual moves (e.g. 'gold rose 1.2% to 2,410') and tie them to the news\n"
    "  only where the link is plausible.\n"
    "- Neutral, precise tone. No hype, no investment advice, no predictions stated as fact.\n\n"
    "Source records:\n"
    "{context}\n\n"
    "Return ONLY valid JSON with this schema:\n"
    "{\n"
    '  "title": "Specific headline naming the main driver and the market it moved (8-14 words)",\n'
    '  "summary": "2-3 sentence standfirst: the main story and its market effect (max 450 chars)",\n'
    '  "article_text": "The article body, following the format instructions",\n'
    '  "impacts": ["Key takeaway naming a market and a direction", "..."],\n'
    '  "importance_score": 1,\n'
    '  "importance_reason": "One sentence naming the market channel (rates, FX, credit, commodities, equities, crypto)",\n'
    '  "references": ["https://a-url-from-the-source-records"]\n'
    "}\n\n"
    "Field rules:\n"
    "- impacts: 3-5 short takeaways, each naming the affected market.\n"
    "- importance_score: integer, 1 = localized/minor, 2 = sector or regional, 3 = global cross-asset.\n"
    "- references: only URLs that appear in the source records, most important first.\n"
)

DEFAULT_AFTERMATH_PROMPT = (
    "You are an institutional financial journalist writing a short retrospective note.\n"
    "You are given a market brief that was published earlier, and the actual price action\n"
    "recorded for its tracked assets in the time since it closed.\n\n"
    "STRICT RULES:\n"
    "- Describe ONLY what already happened in the given price data. Never predict, forecast,\n"
    "  or recommend a future trade direction. Do not use words like 'will', 'expect', 'likely to move',\n"
    "  'should', or 'target'.\n"
    "- If price moves are small or flat, say so plainly rather than inventing significance.\n"
    "- Connect the observed move back to the original brief's stated catalyst when it plausibly explains it,\n"
    "  but do not overstate causation the data doesn't support.\n\n"
    "Original brief:\n"
    "Title: {article_title}\n"
    "Summary: {article_summary}\n"
    "Body: {article_body}\n\n"
    "Observed price action since the brief closed:\n"
    "{price_moves}\n\n"
    "Return ONLY valid JSON with this exact schema:\n"
    "{\n"
    '  "title": "Factual, past-tense headline about what happened to price (6-12 words)",\n'
    '  "summary": "2-3 sentence factual recap of the observed price action (max 400 chars)",\n'
    '  "article_text": "3-5 sentence narrative describing the observed moves and, if supported, how they relate to the original brief. No bullet lists, no predictions.",\n'
    '  "references": []\n'
    "}\n"
)

DEFAULT_FILTER_PROMPT = (
    "You are the NousNews relevance gatekeeper. For each numbered news item, decide whether it is materially\n"
    "relevant to financial markets (rates, FX, credit, commodities, equities, crypto, or broad risk sentiment)\n"
    "and rate its importance.\n\n"
    "- accept: plausible market transmission: central banks, economic data, earnings, deals, commodities,\n"
    "  currencies, crypto, trade, sanctions, regulation, defaults, geopolitics with economic impact.\n"
    "- reject: sports, entertainment, celebrity, lifestyle, local politics without economic impact,\n"
    "  product reviews, promotional or how-to content.\n"
    "- When unsure, accept only if the market link is explicit.\n\n"
    "Items:\n"
    "{items}\n\n"
    "Return ONLY JSON with one entry per item:\n"
    '{"decisions": [{"id": 1, "decision": "accept"}, {"id": 2, "decision": "reject"}]}\n'
)


class AgentConfig(TimeStampedModel):
    llm_enabled = models.BooleanField(default=True)
    use_llm_summaries = models.BooleanField(default=True)
    llm_model = models.CharField(max_length=128, default="gpt-4o-mini")
    llm_base_url = models.URLField(max_length=1000, blank=True, default="")
    llm_api_key = models.CharField(max_length=255, blank=True, default="")
    # Authorization header scheme: "Bearer" for OpenAI-compatible APIs,
    # e.g. "apikey" for ArvanCloud AI.
    llm_auth_scheme = models.CharField(max_length=32, default="Bearer")
    llm_daily_request_budget = models.PositiveIntegerField(default=400)
    llm_temperature = models.FloatField(default=0.1)
    llm_max_output_tokens = models.PositiveIntegerField(default=4000)
    max_context_chars = models.PositiveIntegerField(default=12000)

    loop_interval_minutes = models.FloatField(null=True, blank=True)
    price_loop_interval_seconds = models.FloatField(default=15.0)
    max_items_per_source = models.PositiveIntegerField(default=50)
    user_agent = models.CharField(max_length=255, default="nousnews-agent/1.0 (+https://agent.miyangroup.com)")
    article_prompt_template = models.TextField(default=DEFAULT_ARTICLE_PROMPT)
    filter_prompt_template = models.TextField(blank=True, default=DEFAULT_FILTER_PROMPT)
    signals_prompt_template = models.TextField(
        blank=True,
        default=(
            "You are an institutional signal analyst for global financial markets. Your task: identify the TWO most market-significant\n"
            "events from incoming news that will drive capital allocation in the next 24-72 hours.\n\n"
            "SIGNAL QUALITY CRITERIA:\n"
            "- Magnitude: Central bank policy, major economic data misses, geopolitical escalation, sector disruption\n"
            "- Timing: Fresh catalysts (not old news) with near-term market impact\n"
            "- Clarity: Events with obvious buy/sell implications for specific assets or sectors\n"
            "- Excludes: Celebrity gossip, sports, weather, local politics, product launches with no sector impact\n\n"
            "PRIORITY SIGNAL TYPES (in order):\n"
            "1. Central bank & monetary policy changes (rate hikes/cuts, guidance shifts, QE announcements)\n"
            "2. Economic data beating/missing consensus (employment, inflation, growth figures)\n"
            "3. Geopolitical events with supply chain or energy impacts (sanctions, trade, wars)\n"
            "4. Corporate developments affecting sectoral valuations (major bankruptcies, M&A, earnings misses)\n"
            "5. Fed rate expectations, yield curve moves, currency flash moves\n"
            "6. Commodity shocks (oil, gas, metals) with macro implications\n\n"
            "Context:\n{context}\n\n"
            "Memory (recent signals):\n{memory}\n\n"
            "Return ONLY JSON:\n"
            "{\n"
            '  "signal_1": {"title": "What happened + immediate market impact (6-10 words)", "summary": "Why this matters: causality → asset impact (1-2 sentences, max 200 chars)"},\n'
            '  "signal_2": {"title": "What happened + immediate market impact (6-10 words)", "summary": "Why this matters: causality → asset impact (1-2 sentences, max 200 chars)"}\n'
            "}\n\n"
            "Constraint: Do NOT include signals about sports, entertainment, or non-financial topics.\n"
        ),
    )
    writing_prompt_template = models.TextField(
        blank=True,
        default=(
            "You are writing the executive macro brief for institutional traders and portfolio managers.\n"
            "Synthesize the latest signals into a coherent market narrative that describes WHAT changed, WHY it matters, and WHAT traders should do.\n\n"
            "BRIEF STRUCTURE:\n"
            "- Title: Precise market impact (what/where/catalyst) - 6-12 words\n"
            "- Summary: Event summary + causality + immediate implications for asset prices (2-4 sentences, <600 chars)\n"
            "- Article: Narrative explaining the event, market connections, and expected reactions (3-6 sentences, <1600 chars)\n"
            "- Impacts: Concrete directional impacts on specific assets/sectors/currencies (e.g., 'USD strength vs emerging market FX expected', not 'Markets affected')\n\n"
            "WRITING TONE:\n"
            "- Assume institutional, sophisticated audience. No hype or speculation.\n"
            "- Connect news to specific market reactions: yield curves, credit spreads, equity rotation, commodity prices, FX pairs\n"
            "- Avoid vague adjectives (\"significant\", \"important\"). Use specifics (\"likely +15bps repricing in 10Y yields\").\n\n"
            "Signals:\n{signals}\n\n"
            "Memory (recent context):\n{memory}\n\n"
            "Return ONLY JSON:\n"
            "{\n"
            '  "article_title": "Precise market headline with specific impact (6-12 words)",\n'
            '  "summary": "Strategic summary of event, causality, and market effect (2-4 sentences, max 600 chars)",\n'
            '  "article_text": "Cohesive narrative (3-6 sentences) linking event to: supply/demand, rates, equities, FX, or commodities. No bullet lists.",\n'
            '  "impact_1": {"title": "Specific asset/sector", "summary": "Direction and magnitude", "text": "Why this impact occurs (1-2 sentences)"},\n'
            '  "impact_2": {"title": "Secondary consequence", "summary": "Related market move", "text": "Correlation or spillover effect (1-2 sentences)"},\n'
            '  "references": ["https://url1", "https://url2"]\n'
            "}\n"
        ),
    )
    aftermath_prompt_template = models.TextField(blank=True, default=DEFAULT_AFTERMATH_PROMPT)
    aftermath_min_importance_score = models.PositiveSmallIntegerField(default=2)
    aftermath_delay_hour_minutes = models.PositiveIntegerField(default=60)
    aftermath_delay_day_minutes = models.PositiveIntegerField(default=1440)
    aftermath_delay_week_minutes = models.PositiveIntegerField(default=2880)
    aftermath_delay_month_minutes = models.PositiveIntegerField(default=7200)

    memory_enabled = models.BooleanField(default=True)
    memory_token_limit = models.PositiveIntegerField(default=20000)
    run_forever_enabled = models.BooleanField(default=False)
    run_forever_paused = models.BooleanField(default=False)
    run_once_requested = models.BooleanField(default=False)
    control_password_hash = models.CharField(max_length=255, blank=True, default="")
    control_token_ttl_minutes = models.PositiveIntegerField(default=120)

    class Meta:
        verbose_name = "Agent Configuration"
        verbose_name_plural = "Agent Configuration"


class AgentWorker(TimeStampedModel):
    """Heartbeat/state row (pk=1) written by the `run_forever` worker process.

    The worker runs in its own container; web processes only read this row
    and write control flags on AgentConfig.
    """

    state = models.CharField(max_length=32, default="idle")
    current_action = models.CharField(max_length=64, default="idle")
    started_at = models.DateTimeField(null=True, blank=True)
    heartbeat_at = models.DateTimeField(null=True, blank=True)
    last_news_at = models.DateTimeField(null=True, blank=True)
    last_price_at = models.DateTimeField(null=True, blank=True)
    iterations = models.PositiveIntegerField(default=0)
    last_error = models.TextField(blank=True, default="")


class AgentRun(TimeStampedModel):
    STATUS_RUNNING = "running"
    STATUS_DONE = "done"
    STATUS_FAILED = "failed"

    status = models.CharField(max_length=20, default=STATUS_RUNNING)
    use_llm_filtering = models.BooleanField(default=True)
    started_at = models.DateTimeField(auto_now_add=True)
    ended_at = models.DateTimeField(null=True, blank=True)
    pages_processed = models.PositiveIntegerField(default=0)
    articles_created = models.PositiveIntegerField(default=0)
    queued_urls = models.PositiveIntegerField(default=0)
    llm_requests = models.PositiveIntegerField(default=0)
    llm_prompt_tokens = models.PositiveIntegerField(default=0)
    llm_completion_tokens = models.PositiveIntegerField(default=0)
    last_error = models.TextField(blank=True, default="")

    class Meta:
        ordering = ["-started_at"]


class AgentLogEvent(TimeStampedModel):
    LEVEL_INFO = "info"
    LEVEL_WARN = "warn"
    LEVEL_ERROR = "error"

    STEP_FETCH_RESPONSE = "fetch_response"
    STEP_CLEANED_TEXT = "cleaned_text"
    STEP_LLM_PROMPT = "llm_prompt"
    STEP_LLM_OUTPUT = "llm_output"
    STEP_NEXT_STEP = "next_step"
    STEP_RUN_LIFECYCLE = "run_lifecycle"
    STEP_SOURCE_FETCH = "source_fetch"
    STEP_CARD_GENERATION = "card_generation"
    STEP_LOOP_STATE = "loop_state"
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
        (STEP_RUN_LIFECYCLE, "Run lifecycle"),
        (STEP_SOURCE_FETCH, "Source fetch"),
        (STEP_CARD_GENERATION, "Card generation"),
        (STEP_LOOP_STATE, "Loop state"),
        (STEP_ERROR, "Error"),
    ]

    run = models.ForeignKey(AgentRun, null=True, blank=True, on_delete=models.SET_NULL, related_name="logs")
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
            models.Index(fields=["created_at"]),
            models.Index(fields=["step", "created_at"]),
            models.Index(fields=["run", "created_at"]),
        ]

    def __str__(self) -> str:
        return f"{self.step} ({self.level})"


class NewsSource(ApiKeyMixin, TimeStampedModel):
    SOURCE_API = "api"
    SOURCE_RSS = "rss"

    SOURCE_CHOICES = [
        (SOURCE_API, "API"),
        (SOURCE_RSS, "RSS"),
    ]

    name = models.CharField(max_length=255)
    source_type = models.CharField(max_length=16, choices=SOURCE_CHOICES, default=SOURCE_API)
    base_url = models.URLField(max_length=1000, unique=True)
    enabled = models.BooleanField(default=True)

    api_key = models.CharField(max_length=255, blank=True, default="")
    api_key_param = models.CharField(max_length=64, blank=True, default="")
    api_key_header = models.CharField(max_length=64, blank=True, default="")

    query = models.CharField(max_length=255, blank=True, default="")
    query_param = models.CharField(max_length=64, blank=True, default="")
    language = models.CharField(max_length=64, blank=True, default="")
    language_param = models.CharField(max_length=64, blank=True, default="")
    region = models.CharField(max_length=64, blank=True, default="")
    region_param = models.CharField(max_length=64, blank=True, default="")
    topic = models.CharField(max_length=128, blank=True, default="")
    topic_param = models.CharField(max_length=64, blank=True, default="")
    since_param = models.CharField(max_length=64, blank=True, default="")
    since_format = models.CharField(max_length=32, blank=True, default="iso")

    last_fetched_at = models.DateTimeField(null=True, blank=True)
    failure_count = models.PositiveIntegerField(default=0)
    last_error = models.TextField(blank=True, default="")
    backoff_until = models.DateTimeField(null=True, blank=True)
    rate_limit_seconds = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["name"]

    def __str__(self) -> str:
        return f"{self.name} ({self.source_type})"


class PriceSource(ApiKeyMixin, TimeStampedModel):
    SOURCE_API = "api"
    SOURCE_RSS = "rss"
    SOURCE_EXTERNAL = "external"

    SOURCE_CHOICES = [
        (SOURCE_API, "API"),
        (SOURCE_RSS, "RSS"),
        (SOURCE_EXTERNAL, "External"),
    ]

    name = models.CharField(max_length=255)
    chart_label = models.CharField(max_length=255, blank=True, default="")
    source_type = models.CharField(max_length=16, choices=SOURCE_CHOICES, default=SOURCE_EXTERNAL)
    base_url = models.URLField(max_length=1000, blank=True, default="")
    enabled = models.BooleanField(default=True)

    symbol = models.CharField(max_length=64, blank=True, default="")
    api_key = models.CharField(max_length=255, blank=True, default="")
    api_key_param = models.CharField(max_length=64, blank=True, default="")
    api_key_header = models.CharField(max_length=64, blank=True, default="")
    symbol_param = models.CharField(max_length=64, blank=True, default="")

    price_regex = models.CharField(max_length=255, blank=True, default="")
    price_scale = models.FloatField(default=1.0)

    last_fetched_at = models.DateTimeField(null=True, blank=True)
    failure_count = models.PositiveIntegerField(default=0)
    last_error = models.TextField(blank=True, default="")
    backoff_until = models.DateTimeField(null=True, blank=True)
    rate_limit_seconds = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["name"]

    def __str__(self) -> str:
        return f"{self.name} ({self.symbol or self.source_type})"


class MemoryState(TimeStampedModel):
    content = models.TextField(blank=True, default="")

    class Meta:
        ordering = ["-updated_at"]
