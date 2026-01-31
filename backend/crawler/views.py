from __future__ import annotations

import csv
from io import StringIO

from django.http import HttpResponse
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from crawler.models import CrawlSeed
from crawler.models import CrawlLogEvent
from crawler.serializers import CrawlSeedSerializer, CrawlerConfigSerializer, CrawlLogEventSerializer
from crawler.services import crawler_live_status, get_config, start_crawler_async, CrawlerService


class CrawlerStatusView(APIView):
    def get(self, request):
        return Response(crawler_live_status())


class CrawlerRunView(APIView):
    def post(self, request):
        started = start_crawler_async()
        if not started:
            return Response({"status": "already_running"}, status=status.HTTP_409_CONFLICT)
        return Response({"status": "started"}, status=status.HTTP_202_ACCEPTED)


class CrawlerConfigView(APIView):
    def get(self, request):
        config = get_config()
        return Response(CrawlerConfigSerializer(config).data)

    def put(self, request):
        config = get_config()
        serializer = CrawlerConfigSerializer(config, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)


class CrawlerSeedsView(APIView):
    def get(self, request):
        seeds = CrawlSeed.objects.order_by("url")
        return Response(CrawlSeedSerializer(seeds, many=True).data)

    def post(self, request):
        serializer = CrawlSeedSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        seed = serializer.save()
        return Response(CrawlSeedSerializer(seed).data, status=status.HTTP_201_CREATED)


class CrawlerExportView(APIView):
    def get(self, request):
        buf = StringIO()
        writer = csv.writer(buf)
        service = CrawlerService()
        count = service.export_articles_csv(writer)
        service.close()
        resp = HttpResponse(buf.getvalue(), content_type="text/csv")
        resp["Content-Disposition"] = 'attachment; filename="articles.csv"'
        resp["X-Exported-Rows"] = str(count)
        return resp


class CrawlerLogsView(APIView):
    def get(self, request):
        qs = CrawlLogEvent.objects.order_by("-created_at")
        run_id = request.query_params.get("run_id")
        if run_id:
            qs = qs.filter(run_id=run_id)
        step = request.query_params.get("step")
        if step:
            qs = qs.filter(step=step)
        limit_raw = request.query_params.get("limit", "50")
        try:
            limit = int(limit_raw)
        except ValueError:
            limit = 50
        limit = max(1, min(limit, 200))
        logs = qs[:limit]
        serializer = CrawlLogEventSerializer(logs, many=True)
        return Response({"results": serializer.data, "limit": limit})
