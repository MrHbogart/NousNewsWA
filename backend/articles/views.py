from django.utils import timezone
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.views import APIView

from articles.models import Article, HourlyBrief
from articles.serializers import ArticleIngestSerializer, ArticleSerializer, HourlyBriefSerializer
from articles.services import build_hourly_brief
from core.viewsets import PublicReadModelViewSet


class HealthView(APIView):
    authentication_classes = []
    permission_classes = []

    def get(self, request):
        return Response({"status": "ok"})


class ArticleViewSet(PublicReadModelViewSet):
    queryset = Article.objects.all()
    serializer_class = ArticleSerializer

    @action(detail=False, methods=["post"])
    def ingest(self, request):
        serializer = ArticleIngestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        url = data.pop("url")
        article, created = Article.objects.update_or_create(url=url, defaults=data)
        return Response(
            {"status": "ok", "id": article.id, "created": created},
            status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
        )


class ArticleSummaryView(APIView):
    authentication_classes = []
    permission_classes = []

    def get(self, request):
        limit_raw = request.query_params.get("limit", "5")
        try:
            limit = int(limit_raw)
        except ValueError:
            limit = 5
        limit = max(1, min(limit, 10))

        brief = build_hourly_brief()
        articles = list(
            Article.objects.filter(is_public=True)
            .order_by("-published_at")
            .values("id", "source", "title", "published_at", "url")[:limit]
        )
        summary = brief.summary or "No crawled summaries yet."
        return Response(
            {
                "summary": summary,
                "count": len(articles),
                "items": articles,
                "as_of": timezone.now(),
                "brief_id": brief.id,
                "brief_slug": brief.slug,
                "brief_title": brief.title,
                "brief_hour_start": brief.hour_start,
                "brief_hour_end": brief.hour_end,
            }
        )


class HourlyBriefViewSet(PublicReadModelViewSet):
    queryset = HourlyBrief.objects.all()
    serializer_class = HourlyBriefSerializer
    lookup_field = "slug"

    @action(detail=False, methods=["get"])
    def current(self, request):
        brief = build_hourly_brief()
        serializer = self.get_serializer(brief)
        return Response(serializer.data)

    @action(detail=False, methods=["get"])
    def previous(self, request):
        limit_raw = request.query_params.get("limit", "24")
        try:
            limit = int(limit_raw)
        except ValueError:
            limit = 24
        limit = max(1, min(limit, 168))
        brief = build_hourly_brief()
        previous_items = (
            HourlyBrief.objects.filter(hour_start__lt=brief.hour_start)
            .order_by("-hour_start")[:limit]
        )
        serializer = self.get_serializer(previous_items, many=True)
        return Response(serializer.data)

    @action(detail=False, methods=["get"])
    def headlines(self, request):
        limit_raw = request.query_params.get("limit", "12")
        try:
            limit = int(limit_raw)
        except ValueError:
            limit = 12
        limit = max(1, min(limit, 48))
        items = (
            HourlyBrief.objects.order_by("-hour_start")
            .values("slug", "title", "hour_start")[:limit]
        )
        return Response({"results": list(items)})
