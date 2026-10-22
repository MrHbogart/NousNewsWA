from __future__ import annotations

from datetime import timedelta

from django.utils import timezone
from rest_framework.response import Response
from rest_framework.views import APIView

from articles.models import AssetCandle, AssetSeries
from articles.services import aggregate_candles, price_move, tracked_series

STALE_AFTER = timedelta(minutes=20)  # older last price = market closed (weekend, holiday)


def market_overview() -> dict:
    """Last price, 24h change and a 24h sparkline per tracked instrument.

    The 24h window ends at each series' own last bar, so a closed market shows
    its last session instead of an empty row.
    """
    now = timezone.now()
    rows = []
    for series, label in tracked_series():
        last_at = AssetCandle.objects.filter(series=series).order_by("-timestamp").values_list("timestamp", flat=True).first()
        if last_at is None:
            continue
        start, end = last_at - timedelta(hours=24), last_at + timedelta(minutes=1)
        move = price_move(series, start, end)
        spark = aggregate_candles(series=series, start=start, end=end, interval_minutes=30, max_buckets=49)
        rows.append(
            {
                "symbol": series.symbol,
                "label": label,
                "last": move["close"],
                "change_pct": round(move["change_pct"], 3),
                "high": move["high"],
                "low": move["low"],
                "last_at": last_at,
                "is_stale": now - last_at > STALE_AFTER,
                "sparkline": [round(c["close"], 6) for c in spark],
            }
        )
    return {"results": rows, "generated_at": now}


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


class MarketOverviewView(PublicView):
    def get(self, request):
        return Response(market_overview())
