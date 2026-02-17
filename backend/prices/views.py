from __future__ import annotations

from django.http import JsonResponse
from django.views import View
from django.utils import timezone

from articles.models import AssetSeries
from dataset.models import RawCandle


class HealthView(View):
    def get(self, request):
        return JsonResponse({"status": "ok"})


class SeriesListView(View):
    def get(self, request):
        series = [
            {"symbol": s.symbol, "label": s.label, "timeframe": s.timeframe}
            for s in AssetSeries.objects.all().order_by("symbol")
        ]
        return JsonResponse({"series": series})


class SeriesLatestView(View):
    def get(self, request, symbol: str):
        symbol = symbol.strip()
        # Prefer articles.AssetCandle if present, otherwise fall back to dataset.RawCandle
        latest = (
            RawCandle.objects.filter(asset_symbol=symbol).order_by("-timestamp").first()
        )
        if latest is None:
            return JsonResponse({"symbol": symbol, "latest": None})
        return JsonResponse(
            {
                "symbol": symbol,
                "latest": {
                    "timestamp": latest.timestamp.isoformat(),
                    "open": latest.open,
                    "high": latest.high,
                    "low": latest.low,
                    "close": latest.close,
                    "volume": latest.volume,
                },
            }
        )
