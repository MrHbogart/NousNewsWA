from django.contrib import admin

from .models import Article, HourlyBrief


@admin.register(Article)
class ArticleAdmin(admin.ModelAdmin):
    list_display = ("source", "published_at", "title", "is_public")
    list_filter = ("source", "is_public")
    search_fields = ("title", "body", "url")
    ordering = ("-published_at",)


@admin.register(HourlyBrief)
class HourlyBriefAdmin(admin.ModelAdmin):
    list_display = ("hour_start", "title", "article_count")
    search_fields = ("title", "summary", "slug")
    ordering = ("-hour_start",)
