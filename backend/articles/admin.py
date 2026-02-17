from django.contrib import admin

from .models import Card, CardArticle


@admin.register(Card)
class CardAdmin(admin.ModelAdmin):
    list_display = ("timeframe", "period_start", "status", "title", "article_count")
    list_filter = ("timeframe", "status")
    search_fields = ("slug", "title", "summary", "source_name")
    ordering = ("-period_start",)


@admin.register(CardArticle)
class CardArticleAdmin(admin.ModelAdmin):
    list_display = ("title", "kind", "card", "created_at")
    list_filter = ("kind", "card__timeframe")
    search_fields = ("title", "summary")
    ordering = ("-created_at",)
