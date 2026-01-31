from rest_framework import serializers

from crawler.models import CrawlSeed, CrawlerConfig, CrawlLogEvent


class CrawlSeedSerializer(serializers.ModelSerializer):
    class Meta:
        model = CrawlSeed
        fields = [
            "id",
            "url",
            "config",
            "is_active",
            "last_fetched_at",
            "last_error",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["last_fetched_at", "last_error", "created_at", "updated_at"]


class CrawlerConfigSerializer(serializers.ModelSerializer):
    class Meta:
        model = CrawlerConfig
        fields = [
            "id",
            "llm_enabled",
            "llm_provider",
            "llm_model",
            "llm_base_url",
            "llm_api_key",
            "llm_temperature",
            "llm_max_output_tokens",
            "brief_temperature",
            "brief_max_output_tokens",
            "max_context_chars",
            "max_next_urls",
            "max_articles",
            "max_article_chars",
            "max_pages_per_run",
            "max_depth",
            "brief_max_articles",
            "brief_max_context_chars",
            "request_delay_seconds",
            "user_agent",
            "allow_external_domains",
            "prompt_template",
            "brief_prompt_template",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["created_at", "updated_at"]


class CrawlLogEventSerializer(serializers.ModelSerializer):
    class Meta:
        model = CrawlLogEvent
        fields = [
            "id",
            "run",
            "queue_item",
            "seed_url",
            "url",
            "step",
            "level",
            "message",
            "content",
            "metadata",
            "created_at",
        ]
        read_only_fields = fields
