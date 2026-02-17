from datetime import timedelta
from uuid import UUID

from django.db.models import Case, IntegerField, Value, When
from django.utils import timezone
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from articles.models import Card, CardArticle
from articles.serializers import (
    CardArticleDetailSerializer,
    CardArticleListSerializer,
)


class HealthView(APIView):
    authentication_classes = []
    permission_classes = []

    def get(self, request):
        return Response({"status": "ok"})


class LastHourView(APIView):
    authentication_classes = []
    permission_classes = []

    def get(self, request):
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
            serializer = CardArticleDetailSerializer(current_open_article)
            return Response(serializer.data)

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
            serializer = CardArticleDetailSerializer(article)
            return Response(serializer.data)
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
        return Response(fallback)


class Last24HoursView(APIView):
    authentication_classes = []
    permission_classes = []

    def get(self, request):
        now = timezone.now()
        current_hour_start = now.replace(minute=0, second=0, microsecond=0)
        period_end = current_hour_start + timedelta(hours=1)
        period_start = period_end - timedelta(hours=24)

        current_open_article = (
            CardArticle.objects.select_related("card")
            .filter(
                kind=CardArticle.KIND_MAIN,
                card__timeframe=Card.TIMEFRAME_DAY,
                card__period_start=period_start,
                card__status=Card.STATUS_OPEN,
            )
            .order_by("-updated_at")
            .first()
        )
        if current_open_article:
            serializer = CardArticleDetailSerializer(current_open_article)
            return Response(serializer.data)

        article = (
            CardArticle.objects.select_related("card")
            .filter(
                kind=CardArticle.KIND_MAIN,
                card__timeframe=Card.TIMEFRAME_DAY,
                card__status=Card.STATUS_FINAL,
            )
            .order_by("-card__period_start")
            .first()
        )
        if article:
            serializer = CardArticleDetailSerializer(article)
            return Response(serializer.data)

        fallback = {
            "id": None,
            "timeframe": Card.TIMEFRAME_DAY,
            "period_start": period_start,
            "period_end": period_end,
            "hour_start": period_start,
            "published_at": None,
            "slug": "",
            "title": "Awaiting 24-Hour Financial Market Summary",
            "summary": "No eligible market-moving records were gathered for the current rolling 24-hour window yet.",
            "article_content": "",
            "impacts": [],
            "references": [],
            "article_count": 0,
            "source_name": "",
            "importance_score": 1,
            "importance_reason": "No market-moving records have been accepted yet.",
            "kind": CardArticle.KIND_MAIN,
            "is_daily_summary": True,
            "price_series": [],
            "related_articles": [],
            "created_at": now,
            "updated_at": now,
        }
        return Response(fallback)


class BriefListView(APIView):
    authentication_classes = []
    permission_classes = []

    def get(self, request):
        # Get pagination params (default page=0, limit=10)
        try:
            page = int(request.query_params.get('page', 0))
            limit = int(request.query_params.get('limit', 10))
        except (ValueError, TypeError):
            page = 0
            limit = 10
        
        # Ensure sensible limits
        limit = min(limit, 100)  # Max 100 per page
        limit = max(limit, 1)    # Min 1 per page
        page = max(page, 0)      # Min page 0
        
        # Get all main articles, ordered by period_start (newest first)
        all_articles = (
            CardArticle.objects.select_related("card")
            .filter(
                kind=CardArticle.KIND_MAIN,
                card__status=Card.STATUS_FINAL,
            )
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
            .order_by("timeframe_order", "-card__period_start")
        )
        
        # Get total count
        total_count = all_articles.count()
        
        # Apply pagination
        start = page * limit
        end = start + limit
        items = list(all_articles[start:end])
        
        serializer = CardArticleListSerializer(items, many=True)
        return Response({
            "results": serializer.data,
            "count": total_count,
            "page": page,
            "limit": limit,
        })


class ArticleDetailView(APIView):
    authentication_classes = []
    permission_classes = []

    def get(self, request, pk: str):
        article_qs = CardArticle.objects.select_related("card")
        article = None
        try:
            article_uuid = UUID(str(pk))
            article = article_qs.filter(uuid=article_uuid).first()
        except (ValueError, TypeError):
            article = None
        if not article:
            article = article_qs.filter(slug=pk).first()
        if article:
            serializer = CardArticleDetailSerializer(article)
            return Response(serializer.data)
        return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
