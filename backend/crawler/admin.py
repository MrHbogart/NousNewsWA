from django.contrib import admin

from .models import CrawlQueueItem, CrawlRun, CrawlSeed, CrawlerConfig, CrawlLogEvent


@admin.register(CrawlerConfig)
class CrawlerConfigAdmin(admin.ModelAdmin):
    list_display = (
        "llm_enabled",
        "llm_provider",
        "llm_model",
        "max_pages_per_run",
        "max_depth",
        "request_delay_seconds",
    )


@admin.register(CrawlSeed)
class CrawlSeedAdmin(admin.ModelAdmin):
    list_display = ("url", "config", "is_active", "last_fetched_at")
    list_filter = ("is_active",)
    search_fields = ("url",)


@admin.register(CrawlQueueItem)
class CrawlQueueItemAdmin(admin.ModelAdmin):
    list_display = ("url", "status", "depth", "seed_url", "last_attempt_at", "attempts")
    list_filter = ("status",)
    search_fields = ("url", "seed_url")
    ordering = ("-created_at",)


@admin.register(CrawlRun)
class CrawlRunAdmin(admin.ModelAdmin):
    list_display = (
        "status",
        "started_at",
        "ended_at",
        "pages_processed",
        "articles_created",
        "use_llm_filtering",
        "objective",
    )
    list_filter = ("status",)
    ordering = ("-started_at",)


@admin.register(CrawlLogEvent)
class CrawlLogEventAdmin(admin.ModelAdmin):
    list_display = ("created_at", "level", "step", "message", "seed_url", "url")
    list_filter = ("level", "step")
    search_fields = ("message", "seed_url", "url", "content")
    ordering = ("-created_at",)
