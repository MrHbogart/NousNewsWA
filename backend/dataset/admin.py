from django.contrib import admin

from .models import RawNewsItem, RawCandle


@admin.register(RawNewsItem)
class RawNewsItemAdmin(admin.ModelAdmin):
    list_display = ("source_name", "published_at", "title")
    search_fields = ("title", "summary", "content", "url")
    ordering = ("-published_at",)


@admin.register(RawCandle)
class RawCandleAdmin(admin.ModelAdmin):
    list_display = ("asset_symbol", "timestamp", "open", "high", "low", "close")
    list_filter = ("asset_symbol",)
    ordering = ("-timestamp",)
