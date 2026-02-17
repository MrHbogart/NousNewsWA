from __future__ import annotations

from django.db import models

from core.models import TimeStampedModel

DEFAULT_ARTICLE_PROMPT = (
    "You are the lead editor for NousNews, an institutional-grade financial intelligence platform.\n"
    "Your role: Filter incoming news to extract ONLY economically and financially significant events\n"
    "that directly or indirectly impact global capital markets, currencies, commodities, or asset prices.\n\n"
    "STRICT RELEVANCE CRITERIA (reject if doesn't apply):\n"
    "✓ ACCEPT: Central bank announcements, interest rate changes, monetary policy guidance, QE/QT actions\n"
    "✓ ACCEPT: Economic indicators (inflation, unemployment, GDP, PMI, housing starts, retail sales, industrial production)\n"
    "✓ ACCEPT: Corporate earnings, guidance, M&A, restructuring, major layoffs affecting sectors/markets\n"
    "✓ ACCEPT: Financial markets: stock indices, bond yields, currency moves, commodity price spikes, crypto developments\n"
    "✓ ACCEPT: Geopolitics with economic impact: trade wars, tariffs, sanctions, energy disruptions, supply chain events\n"
    "✓ ACCEPT: Regulatory changes: banking regulations, SEC actions, antitrust rulings, market structure changes\n"
    "✓ ACCEPT: Debt/credit events: sovereign debt, corporate defaults, credit rating changes, banking crises\n"
    "✓ ACCEPT: Energy/commodities: oil/gas disruptions, rare earth supply issues, agricultural shocks\n"
    "✗ REJECT: Sports, entertainment, celebrity news, lifestyle, weather (unless commodity/energy impact)\n"
    "✗ REJECT: Local political events without market implications\n"
    "✗ REJECT: Science/tech unless directly affecting major tech stocks or semiconductors\n"
    "✗ REJECT: Social media gossip, sports transfers, awards shows\n"
    "✗ REJECT: One-off company product launches (low market impact)\n\n"
    "Context:\n"
    "{context}\n\n"
    "Return ONLY valid JSON with this exact schema:\n"
    "{\n"
    '  "title": "Specific market-moving headline (6-12 words, include what/where/why)",\n'
    '  "summary": "2-4 sentence executive summary: event, reason for importance, market impact (max 600 chars)",\n'
    '  "article_text": "Narrative (3-6 sentences): what happened, why it matters economically, expected market reactions. No bullet lists.",\n'
    '  "impacts": ["Concrete impact on asset class/currency/sector", "Secondary trade consequences"],\n'
    '  "importance_score": 1,\n'
    '  "importance_reason": "Single sentence explaining expected cross-asset impact scope",\n'
    '  "references": ["https://url1", "https://url2"]\n'
    "}\n\n"
    "Quality requirements:\n"
    "- Summary must be factual, under 600 chars, assume institutional audience\n"
    "- Avoid vague language like 'significant' or 'important' without specifics\n"
    "- article_text max 1600 chars; explain causality and market connections\n"
    "- Impacts: max 6, each must specify affected market (e.g., 'Long-dated US Treasury yields likely to rise' not 'Markets affected')\n"
    "- importance_score must be an integer: 1 = localized/minor, 2 = regional/sector-wide, 3 = global macro/cross-asset\n"
    "- importance_reason max 180 chars and must name the market channel (rates, FX, credit, commodities, equities)\n"
    "- References must be URLs extracted from context\n"
    "- If content has low relevance to financial markets, return NULL (empty impacts list suggests rejection)\n"
)

DEFAULT_FILTER_PROMPT = (
    "You are the NousNews relevance and impact gatekeeper.\n"
    "Decide if a news item is materially relevant to global financial markets and assign impact importance.\n\n"
    "Relevance standard:\n"
    "- ACCEPT when the item can plausibly reprice rates, FX, credit, commodities, equities, or broad risk sentiment.\n"
    "- REJECT if primarily sports, entertainment, celebrity, lifestyle, or local politics without economic transmission.\n"
    "- Prefer caution: if uncertain, accept only when concrete market transmission is explicit.\n\n"
    "Importance scale:\n"
    "- 1 = localized/minor, limited to a single issuer or niche market\n"
    "- 2 = regional/sector level, meaningful but not global regime-shifting\n"
    "- 3 = global/cross-asset catalyst, likely to influence multiple major markets\n\n"
    "Input:\n"
    "Title: {title}\n"
    "Summary: {summary}\n"
    "Content: {content}\n"
    "Heuristic score: {heuristic_score}\n\n"
    "Return ONLY JSON:\n"
    "{\n"
    '  "decision": "accept|reject",\n'
    '  "importance_score": 1,\n'
    '  "confidence": 0.0,\n'
    '  "reason": "One sentence explaining market relevance decision"\n'
    "}\n"
)


class AgentConfig(TimeStampedModel):
    llm_enabled = models.BooleanField(default=True)
    use_llm_summaries = models.BooleanField(default=True)
    llm_model = models.CharField(max_length=128, default="gpt-4o-mini")
    llm_base_url = models.URLField(max_length=1000, blank=True, default="")
    llm_api_key = models.CharField(max_length=255, blank=True, default="")
    llm_temperature = models.FloatField(default=0.1)
    llm_max_output_tokens = models.PositiveIntegerField(default=1400)
    max_context_chars = models.PositiveIntegerField(default=12000)

    loop_interval_minutes = models.FloatField(null=True, blank=True)
    price_loop_interval_seconds = models.FloatField(default=60.0)
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
    memory_enabled = models.BooleanField(default=True)
    memory_token_limit = models.PositiveIntegerField(default=20000)
    run_forever_enabled = models.BooleanField(default=False)
    control_password_hash = models.CharField(max_length=255, blank=True, default="")
    control_token_ttl_minutes = models.PositiveIntegerField(default=120)

    class Meta:
        verbose_name = "Agent Configuration"
        verbose_name_plural = "Agent Configuration"


class AgentRun(TimeStampedModel):
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
            models.Index(fields=["step", "created_at"]),
            models.Index(fields=["run", "created_at"]),
        ]

    def __str__(self) -> str:
        return f"{self.step} ({self.level})"


class NewsSource(TimeStampedModel):
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


class PriceSource(TimeStampedModel):
    SOURCE_API = "api"
    SOURCE_RSS = "rss"
    SOURCE_EXTERNAL = "external"

    SOURCE_CHOICES = [
        (SOURCE_API, "API"),
        (SOURCE_RSS, "RSS"),
        (SOURCE_EXTERNAL, "External"),
    ]

    name = models.CharField(max_length=255)
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
