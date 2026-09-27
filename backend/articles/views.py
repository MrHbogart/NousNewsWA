from datetime import timedelta
from uuid import UUID

from django.db.models import Case, IntegerField, Value, When
from django.utils import timezone
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from agent.services.runtime import worker_status
from articles.models import Card, CardArticle
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
    """The open current-hour brief, else the latest final one, else a placeholder."""
    now = timezone.now()
    current_hour_start = now.replace(minute=0, second=0, microsecond=0)

    current_open_article = (
        CardArticle.objects.select_related("card")
        .filter(
            kind=CardArticle.KIND_MAIN,
            card__timeframe=Card.TIMEFRAME_HOUR,
            card__period_start=current_hour_start,
            card__status=Card.STATUS_OPEN,
        )
        .order_by("-updated_at")
        .first()
    )
    if current_open_article:
        return CardArticleDetailSerializer(current_open_article).data

    article = (
        CardArticle.objects.select_related("card")
        .filter(
            kind=CardArticle.KIND_MAIN,
            card__timeframe=Card.TIMEFRAME_HOUR,
            card__status=Card.STATUS_FINAL,
        )
        .order_by("-card__period_start")
        .first()
    )
    if article:
        return CardArticleDetailSerializer(article).data
    fallback = {
        "id": None,
        "timeframe": Card.TIMEFRAME_HOUR,
        "period_start": now.replace(minute=0, second=0, microsecond=0),
        "period_end": (now.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)),
        "hour_start": now.replace(minute=0, second=0, microsecond=0),
        "published_at": None,
        "slug": "",
        "title": "Awaiting Next Finalized Financial Market Brief",
        "summary": "No finalized high-impact financial updates were published for the latest closed hour yet.",
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
        "created_at": now,
        "updated_at": now,
    }
    return fallback


class LastHourView(APIView):
    authentication_classes = []
    permission_classes = []

    def get(self, request):
        return Response(last_hour_payload())


def briefs_payload(page: int = 0, limit: int = 10) -> dict:
    limit = max(1, min(limit, 100))
    page = max(page, 0)
    # Newest period end first; when periods end together the wider timeframe
    # (month > week > day > hour) comes first.
    all_articles = (
        CardArticle.objects.select_related("card")
        .filter(kind=CardArticle.KIND_MAIN, card__status=Card.STATUS_FINAL)
        .annotate(
            timeframe_order=Case(
                When(card__timeframe=Card.TIMEFRAME_HOUR, then=Value(1)),
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
