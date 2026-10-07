from uuid import UUID

from django.db.models import Case, IntegerField, Max, Value, When
from django.utils import timezone
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from agent.services.runtime import worker_status
from articles.models import Card, CardArticle
from articles.services import get_period_window
from articles.serializers import (
    CardArticleDetailSerializer,
    CardArticleListSerializer,
)


class HealthView(APIView):
    authentication_classes = []
    permission_classes = []

    def get(self, request):
        # Always 200 while the web process is up (container healthcheck);
        # `agent` shows whether the separate worker is alive and syncing.
        status_ = worker_status()
        return Response(
            {
                "status": "ok",
                "agent": {
                    key: status_[key]
                    for key in ("running", "worker_online", "state", "last_heartbeat_at", "last_news_run_at", "last_price_sync_at")
                },
            }
        )


def last_hour_payload() -> dict:
    """The open current intraday brief, else the latest final one, else a placeholder."""
    now = timezone.now()
    block_start, block_end = get_period_window(now, Card.TIMEFRAME_INTRADAY)
    intraday = CardArticle.objects.select_related("card").filter(
        kind=CardArticle.KIND_MAIN, card__timeframe=Card.TIMEFRAME_INTRADAY
    )

    article = (
        intraday.filter(card__period_start=block_start, card__status=Card.STATUS_OPEN).order_by("-updated_at").first()
        or intraday.filter(card__status=Card.STATUS_FINAL).order_by("-card__period_start").first()
    )
    if article:
        return CardArticleDetailSerializer(article).data
    return {
        "id": None,
        "timeframe": Card.TIMEFRAME_INTRADAY,
        "period_start": block_start,
        "period_end": block_end,
        "hour_start": block_start,
        "published_at": None,
        "slug": "",
        "title": "Awaiting Next Finalized Financial Market Brief",
        "summary": "No finalized high-impact financial updates were published for the latest closed period yet.",
        "article_content": "",
        "impacts": [],
        "references": [],
        "article_count": 0,
        "source_name": "",
        "importance_score": 1,
        "importance_reason": "No market-moving records have been accepted yet.",
        "kind": CardArticle.KIND_MAIN,
        "is_daily_summary": False,
        "price_series": [],
        "related_articles": [],
        "day_article": None,
        "created_at": now,
        "updated_at": now,
    }


class LastHourView(APIView):
    authentication_classes = []
    permission_classes = []

    def get(self, request):
        return Response(last_hour_payload())


def _collapsed_day_end():
    """End of the latest finalized day card: intraday briefs before it are folded into day articles."""
    return Card.objects.filter(timeframe=Card.TIMEFRAME_DAY, status=Card.STATUS_FINAL).aggregate(
        end=Max("period_end")
    )["end"]


def visible_final_articles(kinds=(CardArticle.KIND_MAIN,)):
    """Final articles a reader (or crawler) should see: old days show as one day article each."""
    qs = CardArticle.objects.select_related("card").filter(kind__in=kinds, card__status=Card.STATUS_FINAL)
    day_end = _collapsed_day_end()
    if day_end:
        qs = qs.exclude(kind=CardArticle.KIND_MAIN, card__timeframe=Card.TIMEFRAME_INTRADAY, card__period_start__lt=day_end)
    return qs


def briefs_payload(page: int = 0, limit: int = 10) -> dict:
    limit = max(1, min(limit, 100))
    page = max(page, 0)
    # Newest period end first; when periods end together the wider timeframe
    # (month > week > day > intraday) comes first.
    all_articles = (
        visible_final_articles()
        .annotate(
            timeframe_order=Case(
                When(card__timeframe=Card.TIMEFRAME_INTRADAY, then=Value(1)),
                When(card__timeframe=Card.TIMEFRAME_DAY, then=Value(2)),
                When(card__timeframe=Card.TIMEFRAME_WEEK, then=Value(3)),
                When(card__timeframe=Card.TIMEFRAME_MONTH, then=Value(4)),
                default=Value(9),
                output_field=IntegerField(),
            )
        )
        .order_by("-card__period_end", "-timeframe_order")
    )
    items = list(all_articles[page * limit : (page + 1) * limit])
    return {
        "results": CardArticleListSerializer(items, many=True).data,
        "count": all_articles.count(),
        "page": page,
        "limit": limit,
    }


class BriefListView(APIView):
    authentication_classes = []
    permission_classes = []

    def get(self, request):
        try:
            page = int(request.query_params.get("page", 0))
            limit = int(request.query_params.get("limit", 10))
        except (ValueError, TypeError):
            page, limit = 0, 10
        return Response(briefs_payload(page, limit))


def sitemap_payload() -> list[dict]:
    # ponytail: one flat list, capped at the sitemap protocol's 50k URLs; add a sitemap index past that.
    rows = (
        visible_final_articles(kinds=(CardArticle.KIND_MAIN, CardArticle.KIND_AFTERMATH))
        .exclude(slug="")
        .order_by("-card__period_end")
        .values("slug", "updated_at")[:50000]
    )
    return list(rows)


class SitemapView(APIView):
    authentication_classes = []
    permission_classes = []

    def get(self, request):
        return Response({"results": sitemap_payload()})


def article_payload(pk: str) -> dict | None:
    """Article by UUID or slug."""
    article_qs = CardArticle.objects.select_related("card")
    article = None
    try:
        article = article_qs.filter(uuid=UUID(str(pk))).first()
    except (ValueError, TypeError):
        pass
    if not article:
        article = article_qs.filter(slug=pk).first()
    return CardArticleDetailSerializer(article).data if article else None


class ArticleDetailView(APIView):
    authentication_classes = []
    permission_classes = []

    def get(self, request, pk: str):
        payload = article_payload(pk)
        if payload is None:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        return Response(payload)
