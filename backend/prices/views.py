from __future__ import annotations

from rest_framework.response import Response
from rest_framework.views import APIView

from articles.models import AssetCandle, AssetSeries


class PublicView(APIView):
    authentication_classes = []
    permission_classes = []


class HealthView(PublicView):
    def get(self, request):
        return Response({"status": "ok"})


class SeriesListView(PublicView):
    def get(self, request):
        series = [
            {"symbol": s.symbol, "label": s.label, "timeframe": s.timeframe}
            for s in AssetSeries.objects.all().order_by("symbol")
        ]
        return Response({"series": series})


class SeriesLatestView(PublicView):
    def get(self, request, symbol: str):
        symbol = symbol.strip()
        latest = AssetCandle.objects.filter(series__symbol=symbol).order_by("-timestamp").first()
        if latest is None:
            return Response({"symbol": symbol, "latest": None})
        return Response(
            {
                "symbol": symbol,
                "latest": {
                    "timestamp": latest.timestamp,
                    "open": latest.open,
                    "high": latest.high,
                    "low": latest.low,
                    "close": latest.close,
                    "volume": latest.volume,
                },
            }
        )
