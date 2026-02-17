from __future__ import annotations

from django.core.management.base import BaseCommand

from agent.models import AgentConfig, MemoryState, NewsSource, PriceSource
from articles.models import AssetSeries


NEWS_RSS_SOURCES = [
    {
        "name": "Federal Reserve - All Press Releases",
        "base_url": "https://www.federalreserve.gov/feeds/press_all.xml",
        "enabled": True,
        "rate_limit_seconds": 30,
    },
    {
        "name": "Federal Reserve - Monetary Policy",
        "base_url": "https://www.federalreserve.gov/feeds/press_monetary.xml",
        "enabled": True,
        "rate_limit_seconds": 30,
    },
    {
        "name": "Federal Reserve - Speeches",
        "base_url": "https://www.federalreserve.gov/feeds/speeches.xml",
        "enabled": True,
        "rate_limit_seconds": 60,
    },
    {
        "name": "Federal Reserve - Testimony",
        "base_url": "https://www.federalreserve.gov/feeds/testimony.xml",
        "enabled": True,
        "rate_limit_seconds": 60,
    },
    {
        "name": "ECB - Press & Speeches",
        "base_url": "https://www.ecb.europa.eu/rss/press.html",
        "enabled": True,
        "rate_limit_seconds": 60,
    },
    {
        "name": "ECB - Publications",
        "base_url": "https://www.ecb.europa.eu/rss/pub.html",
        "enabled": True,
        "rate_limit_seconds": 120,
    },
    {
        "name": "Bank of England - News",
        "base_url": "https://www.bankofengland.co.uk/rss/news",
        "enabled": True,
        "rate_limit_seconds": 60,
    },
    {
        "name": "Bank of Japan - What's New",
        "base_url": "https://www.boj.or.jp/en/rss/whatsnew.xml",
        "enabled": True,
        "rate_limit_seconds": 60,
    },
    {
        "name": "RBA - Research & Policy",
        "base_url": "https://www.rba.gov.au/rss/rss-cb-rdp.xml",
        "enabled": True,
        "rate_limit_seconds": 120,
    },
    {
        "name": "Swiss National Bank - News",
        "base_url": "https://www.snb.ch/public/en/rss/news",
        "enabled": True,
        "rate_limit_seconds": 120,
    },
    {
        "name": "CentralBanking - Monetary Policy",
        "base_url": "https://www.centralbanking.com/feeds/rss/category/central-banks/monetary-policy",
        "enabled": True,
        "rate_limit_seconds": 120,
    },
]


NEWS_API_SOURCES = [
    {
        "name": "Finnhub - General Financial News",
        "base_url": "https://finnhub.io/api/v1/news",
        "source_type": NewsSource.SOURCE_API,
        "enabled": False,
        "api_key_param": "token",
        "api_key_header": "X-Finnhub-Token",
        "query_param": "category",
        "query": "general",
        "rate_limit_seconds": 2,
    },
    {
        "name": "Alpha Vantage - News Sentiment (Macro)",
        "base_url": "https://www.alphavantage.co/query",
        "source_type": NewsSource.SOURCE_API,
        "enabled": False,
        "api_key_param": "apikey",
        "topic_param": "function",
        "topic": "NEWS_SENTIMENT",
        "query_param": "topics",
        "query": "economy_macro,financial_markets",
        "language_param": "sort",
        "language": "LATEST",
        "rate_limit_seconds": 20,
    },
    {
        "name": "NewsAPI - Central Banks & Markets",
        "base_url": "https://newsapi.org/v2/everything",
        "source_type": NewsSource.SOURCE_API,
        "enabled": False,
        "api_key_param": "apiKey",
        "query_param": "q",
        "query": "(federal reserve OR central bank OR inflation OR treasury yields OR forex OR commodities)",
        "language_param": "language",
        "language": "en",
        "topic_param": "sortBy",
        "topic": "publishedAt",
        "since_param": "from",
        "since_format": "rfc3339",
        "rate_limit_seconds": 6,
    },
    {
        "name": "FRED - Release Updates",
        "base_url": "https://api.stlouisfed.org/fred/releases/updates",
        "source_type": NewsSource.SOURCE_API,
        "enabled": False,
        "api_key_param": "api_key",
        "query_param": "file_type",
        "query": "json",
        "language_param": "limit",
        "language": "100",
        "region_param": "order_by",
        "region": "last_updated",
        "topic_param": "sort_order",
        "topic": "desc",
        "rate_limit_seconds": 30,
    },
    {
        "name": "GNews - Financial Markets",
        "base_url": "https://gnews.io/api/v4/search",
        "source_type": NewsSource.SOURCE_API,
        "enabled": False,
        "api_key_param": "apikey",
        "query_param": "q",
        "query": "central bank OR inflation OR treasury yield OR forex OR commodities",
        "language_param": "lang",
        "language": "en",
        "region_param": "max",
        "region": "25",
        "rate_limit_seconds": 6,
    },
]


LEGACY_NEWS_API_SOURCES = [
    {"name": "NewsDataHub", "base_url": "https://api.newsdatahub.com/v1/news", "source_type": NewsSource.SOURCE_API, "enabled": False},
    {"name": "NewsAPI Everything", "base_url": "https://newsapi.org/v2/everything", "source_type": NewsSource.SOURCE_API, "enabled": False, "api_key_param": "apiKey"},
    {"name": "NewsAPI Top Headlines", "base_url": "https://newsapi.org/v2/top-headlines", "source_type": NewsSource.SOURCE_API, "enabled": False, "api_key_param": "apiKey"},
    {"name": "NewsData.io", "base_url": "https://newsdata.io/api/1/news", "source_type": NewsSource.SOURCE_API, "enabled": False},
    {"name": "Mediastack", "base_url": "https://api.mediastack.com/v1/news", "source_type": NewsSource.SOURCE_API, "enabled": False},
    {"name": "Bing News Search", "base_url": "https://api.bing.microsoft.com/v7.0/news/search", "source_type": NewsSource.SOURCE_API, "enabled": False},
    {"name": "TheNewsAPI", "base_url": "https://www.thenewsapi.com/", "source_type": NewsSource.SOURCE_API, "enabled": False},
    {"name": "AllNewsAPI", "base_url": "https://api.allnewsapi.com/search", "source_type": NewsSource.SOURCE_API, "enabled": False},
]


LEGACY_NEWS_RSS_SOURCES = [
    {"name": "CNN", "base_url": "http://rss.cnn.com/rss/edition.rss", "enabled": True},
    {"name": "NYTimes", "base_url": "https://rss.nytimes.com/services/xml/rss/nyt/HomePage.xml", "enabled": True},
    {"name": "BBC World", "base_url": "https://feeds.bbci.co.uk/news/world/rss.xml", "enabled": True},
    {"name": "Washington Post World", "base_url": "https://feeds.washingtonpost.com/rss/world", "enabled": True},
    {"name": "NBC News", "base_url": "https://feeds.nbcnews.com/feeds/topstories", "enabled": True},
    {"name": "Fox News", "base_url": "https://feeds.foxnews.com/foxnews/latest", "enabled": True},
    {"name": "Al Jazeera", "base_url": "https://www.aljazeera.com/xml/rss/all.xml", "enabled": True},
    {"name": "Times of India", "base_url": "https://timesofindia.indiatimes.com/rssfeedstopstories.cms", "enabled": True},
    {"name": "Le Monde", "base_url": "https://www.lemonde.fr/en/rss/une.xml", "enabled": True},
    {"name": "Lenta", "base_url": "https://lenta.ru/rss", "enabled": True},
    {"name": "Gazeta", "base_url": "https://www.gazeta.ru/export/rss/first.xml", "enabled": True},
    {"name": "Newsru", "base_url": "https://rss.newsru.com/top/big/", "enabled": True},
    {"name": "RT", "base_url": "https://www.rt.com/rss/", "enabled": True},
    {"name": "Meduza", "base_url": "https://meduza.io/rss/all", "enabled": True},
]


ASSET_SERIES = [
    {"symbol": "USDidx", "label": "USD Index (Legacy)", "timeframe": "1m"},
    {"symbol": "XAUUSD", "label": "Gold Spot (Legacy)", "timeframe": "1m"},
    {"symbol": "BTCUSD", "label": "Bitcoin (Legacy)", "timeframe": "1m"},
    {"symbol": "S&P500", "label": "S&P 500 (Legacy)", "timeframe": "1m"},
    {"symbol": "DX-Y.NYB", "label": "US Dollar Index (DXY)", "timeframe": "1m"},
    {"symbol": "XAUUSD=X", "label": "Gold Spot (XAUUSD)", "timeframe": "1m"},
    {"symbol": "BTC-USD", "label": "Bitcoin (BTCUSD)", "timeframe": "1m"},
    {"symbol": "^GSPC", "label": "S&P 500 Index", "timeframe": "1m"},
    {"symbol": "DTWEXBGS", "label": "Trade-Weighted USD Index (FRED)", "timeframe": "1m"},
    {"symbol": "DGS10", "label": "US 10Y Treasury Yield (FRED)", "timeframe": "1m"},
    {"symbol": "FEDFUNDS", "label": "Fed Funds Effective Rate (FRED)", "timeframe": "1m"},
    {"symbol": "US_TREASURY_AVG_RATE", "label": "US Treasury Average Interest Rate", "timeframe": "1m"},
]


PRICE_SOURCES = [
    {
        "name": "CoinGecko BTC Spot (Free)",
        "base_url": "https://api.coingecko.com/api/v3/simple/price?ids=bitcoin&vs_currencies=usd",
        "symbol": "BTC-USD",
        "chart_label": "Bitcoin",
        "source_type": PriceSource.SOURCE_API,
        "enabled": True,
        "price_regex": r"\"usd\"\s*:\s*(?P<price>-?\d+(?:\.\d+)?)",
        "rate_limit_seconds": 20,
    },
    {
        "name": "US Treasury Avg Interest Rate (Free)",
        "base_url": "https://api.fiscaldata.treasury.gov/services/api/fiscal_service/v1/accounting/od/avg_interest_rates?sort=-record_date&page[size]=1",
        "symbol": "US_TREASURY_AVG_RATE",
        "chart_label": "US Treasury Avg Rate",
        "source_type": PriceSource.SOURCE_API,
        "enabled": True,
        "price_regex": r"\"avg_interest_rate_amt\"\s*:\s*\"?(?P<price>-?\d+(?:\.\d+)?)\"?",
        "rate_limit_seconds": 300,
    },
    {
        "name": "FRED DTWEXBGS (API Key)",
        "base_url": "https://api.stlouisfed.org/fred/series/observations?series_id=DTWEXBGS&file_type=json&sort_order=desc&limit=1",
        "symbol": "DTWEXBGS",
        "chart_label": "US Dollar Index",
        "source_type": PriceSource.SOURCE_API,
        "enabled": False,
        "api_key_param": "api_key",
        "rate_limit_seconds": 300,
    },
    {
        "name": "FRED DGS10 (API Key)",
        "base_url": "https://api.stlouisfed.org/fred/series/observations?series_id=DGS10&file_type=json&sort_order=desc&limit=1",
        "symbol": "DGS10",
        "chart_label": "US 10Y Yield",
        "source_type": PriceSource.SOURCE_API,
        "enabled": False,
        "api_key_param": "api_key",
        "rate_limit_seconds": 300,
    },
    {
        "name": "FRED FEDFUNDS (API Key)",
        "base_url": "https://api.stlouisfed.org/fred/series/observations?series_id=FEDFUNDS&file_type=json&sort_order=desc&limit=1",
        "symbol": "FEDFUNDS",
        "chart_label": "Fed Funds Rate",
        "source_type": PriceSource.SOURCE_API,
        "enabled": False,
        "api_key_param": "api_key",
        "rate_limit_seconds": 300,
    },
    {
        "name": "Finnhub BTC Quote (API Key)",
        "base_url": "https://finnhub.io/api/v1/quote?symbol=BINANCE:BTCUSDT",
        "symbol": "BTC-USD",
        "chart_label": "Bitcoin",
        "source_type": PriceSource.SOURCE_API,
        "enabled": False,
        "api_key_param": "token",
        "api_key_header": "X-Finnhub-Token",
        "rate_limit_seconds": 2,
    },
    {
        "name": "Finnhub Gold Quote (API Key)",
        "base_url": "https://finnhub.io/api/v1/quote?symbol=OANDA:XAU_USD",
        "symbol": "XAUUSD=X",
        "chart_label": "Gold",
        "source_type": PriceSource.SOURCE_API,
        "enabled": False,
        "api_key_param": "token",
        "api_key_header": "X-Finnhub-Token",
        "rate_limit_seconds": 2,
    },
    {
        "name": "Finnhub S&P Proxy Quote (API Key)",
        "base_url": "https://finnhub.io/api/v1/quote?symbol=SPY",
        "symbol": "^GSPC",
        "chart_label": "S&P 500",
        "source_type": PriceSource.SOURCE_API,
        "enabled": False,
        "api_key_param": "token",
        "api_key_header": "X-Finnhub-Token",
        "rate_limit_seconds": 2,
    },
    {
        "name": "TwelveData DXY (API Key)",
        "base_url": "https://api.twelvedata.com/price?symbol=DXY",
        "symbol": "DX-Y.NYB",
        "chart_label": "US Dollar Index",
        "source_type": PriceSource.SOURCE_API,
        "enabled": False,
        "api_key_param": "apikey",
        "rate_limit_seconds": 6,
    },
    {
        "name": "TwelveData Gold (API Key)",
        "base_url": "https://api.twelvedata.com/price?symbol=XAU/USD",
        "symbol": "XAUUSD=X",
        "chart_label": "Gold",
        "source_type": PriceSource.SOURCE_API,
        "enabled": False,
        "api_key_param": "apikey",
        "rate_limit_seconds": 6,
    },
    {
        "name": "TwelveData SPX (API Key)",
        "base_url": "https://api.twelvedata.com/price?symbol=SPX",
        "symbol": "^GSPC",
        "chart_label": "S&P 500",
        "source_type": PriceSource.SOURCE_API,
        "enabled": False,
        "api_key_param": "apikey",
        "rate_limit_seconds": 6,
    },
    {
        "name": "Alpha Vantage XAUUSD (API Key)",
        "base_url": "https://www.alphavantage.co/query?function=CURRENCY_EXCHANGE_RATE&from_currency=XAU&to_currency=USD",
        "symbol": "XAUUSD=X",
        "chart_label": "Gold",
        "source_type": PriceSource.SOURCE_API,
        "enabled": False,
        "api_key_param": "apikey",
        "price_regex": r"\"5\. Exchange Rate\"\s*:\s*\"(?P<price>-?\d+(?:\.\d+)?)\"",
        "rate_limit_seconds": 20,
    },
    {
        "name": "Alpha Vantage Treasury Yield 10Y (API Key)",
        "base_url": "https://www.alphavantage.co/query?function=TREASURY_YIELD&maturity=10year&interval=daily",
        "symbol": "DGS10",
        "chart_label": "US 10Y Yield",
        "source_type": PriceSource.SOURCE_API,
        "enabled": False,
        "api_key_param": "apikey",
        "rate_limit_seconds": 20,
    },
]


LEGACY_PRICE_SOURCES = [
    {
        "name": "USD Index (fixture)",
        "base_url": "fixtures/USDidx.csv",
        "symbol": "USDidx",
        "chart_label": "USD Index",
        "source_type": PriceSource.SOURCE_RSS,
        "enabled": False,
    },
    {
        "name": "XAUUSD (fixture)",
        "base_url": "fixtures/XAUUSD.csv",
        "symbol": "XAUUSD",
        "chart_label": "Gold",
        "source_type": PriceSource.SOURCE_RSS,
        "enabled": False,
    },
    {
        "name": "BTCUSD (fixture)",
        "base_url": "fixtures/BTCUSD.csv",
        "symbol": "BTCUSD",
        "chart_label": "Bitcoin",
        "source_type": PriceSource.SOURCE_RSS,
        "enabled": False,
    },
    {
        "name": "S&P500 (fixture)",
        "base_url": "fixtures/SP500.csv",
        "symbol": "S&P500",
        "chart_label": "S&P 500",
        "source_type": PriceSource.SOURCE_RSS,
        "enabled": False,
    },
]


class Command(BaseCommand):
    help = "Seed curated central-bank news sources and diversified price provider templates."

    def handle(self, *args, **options):
        created_news = 0
        created_prices = 0
        updated_news = 0
        updated_prices = 0

        for definition in [
            *NEWS_RSS_SOURCES,
            *LEGACY_NEWS_RSS_SOURCES,
            *NEWS_API_SOURCES,
            *LEGACY_NEWS_API_SOURCES,
        ]:
            source, was_created = NewsSource.objects.get_or_create(
                base_url=definition["base_url"],
                defaults=self._news_defaults(definition),
            )
            if was_created:
                created_news += 1
            if self._apply_missing_news_fields(source, definition):
                updated_news += 1

        for entry in ASSET_SERIES:
            series, _ = AssetSeries.objects.get_or_create(
                symbol=entry["symbol"],
                defaults={"label": entry["label"], "timeframe": entry.get("timeframe", "1m")},
            )
            updates = []
            if not (series.label or "").strip() and entry.get("label"):
                series.label = entry["label"]
                updates.append("label")
            if not (series.timeframe or "").strip() and entry.get("timeframe"):
                series.timeframe = entry["timeframe"]
                updates.append("timeframe")
            if updates:
                series.save(update_fields=updates)

        for definition in [*PRICE_SOURCES, *LEGACY_PRICE_SOURCES]:
            source, was_created = PriceSource.objects.get_or_create(
                name=definition["name"],
                symbol=definition["symbol"],
                defaults=self._price_defaults(definition),
            )
            if was_created:
                created_prices += 1
            if self._apply_missing_price_fields(source, definition):
                updated_prices += 1

        # Disable legacy fixture URLs so production loops do not retry local CSV paths.
        PriceSource.objects.filter(base_url__startswith="fixtures/").update(enabled=False)

        config, _ = AgentConfig.objects.get_or_create()
        config_updates = {
            "llm_base_url": "https://openrouter.ai/api/v1",
            "llm_max_output_tokens": 20000,
            "loop_interval_minutes": 15.0,
            "price_loop_interval_seconds": 30.0,
            "max_items_per_source": 100,
            "max_context_chars": 50000,
        }
        if config_updates:
            for key, value in config_updates.items():
                setattr(config, key, value)
            config.save(update_fields=list(config_updates.keys()))

        existing_states = list(MemoryState.objects.order_by("-updated_at"))
        if not existing_states:
            MemoryState.objects.create()
        elif len(existing_states) > 1:
            keeper = existing_states[0]
            MemoryState.objects.exclude(pk=keeper.pk).delete()

        self.stdout.write(
            self.style.SUCCESS(
                f"Seed complete: news created={created_news}, news updated={updated_news}, "
                f"price created={created_prices}, price updated={updated_prices}"
            )
        )

    @staticmethod
    def _news_defaults(definition: dict) -> dict:
        return {
            "name": definition["name"],
            "source_type": definition.get("source_type", NewsSource.SOURCE_RSS),
            "enabled": definition.get("enabled", False),
            "api_key_param": definition.get("api_key_param", ""),
            "api_key_header": definition.get("api_key_header", ""),
            "query_param": definition.get("query_param", ""),
            "query": definition.get("query", ""),
            "language_param": definition.get("language_param", ""),
            "language": definition.get("language", ""),
            "region_param": definition.get("region_param", ""),
            "region": definition.get("region", ""),
            "topic_param": definition.get("topic_param", ""),
            "topic": definition.get("topic", ""),
            "since_param": definition.get("since_param", ""),
            "since_format": definition.get("since_format", "iso"),
            "rate_limit_seconds": definition.get("rate_limit_seconds", 0),
        }

    @staticmethod
    def _price_defaults(definition: dict) -> dict:
        return {
            "base_url": definition.get("base_url", ""),
            "source_type": definition.get("source_type", PriceSource.SOURCE_API),
            "enabled": definition.get("enabled", False),
            "chart_label": definition.get("chart_label", ""),
            "api_key_param": definition.get("api_key_param", ""),
            "api_key_header": definition.get("api_key_header", ""),
            "symbol_param": definition.get("symbol_param", ""),
            "price_regex": definition.get("price_regex", ""),
            "price_scale": definition.get("price_scale", 1.0),
            "rate_limit_seconds": definition.get("rate_limit_seconds", 0),
        }

    def _apply_missing_news_fields(self, source: NewsSource, definition: dict) -> bool:
        updated_fields: list[str] = []
        fallback_values = self._news_defaults(definition)
        for field, value in fallback_values.items():
            if field == "enabled":
                continue
            current = getattr(source, field)
            if self._is_blank(current) and not self._is_blank(value):
                setattr(source, field, value)
                updated_fields.append(field)
        if self._is_blank(source.name):
            source.name = definition["name"]
            updated_fields.append("name")
        if updated_fields:
            source.save(update_fields=sorted(set(updated_fields)))
            return True
        return False

    def _apply_missing_price_fields(self, source: PriceSource, definition: dict) -> bool:
        updated_fields: list[str] = []
        fallback_values = self._price_defaults(definition)
        for field, value in fallback_values.items():
            if field == "enabled":
                continue
            current = getattr(source, field)
            if self._is_blank(current) and not self._is_blank(value):
                setattr(source, field, value)
                updated_fields.append(field)
        if self._is_blank(source.base_url) and definition.get("base_url"):
            source.base_url = definition["base_url"]
            updated_fields.append("base_url")
        if updated_fields:
            source.save(update_fields=sorted(set(updated_fields)))
            return True
        return False

    @staticmethod
    def _is_blank(value: object) -> bool:
        if value is None:
            return True
        if isinstance(value, str):
            return not value.strip()
        if isinstance(value, (int, float)):
            return value == 0
        return False
