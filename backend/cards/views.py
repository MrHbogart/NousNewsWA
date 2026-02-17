from __future__ import annotations

from django.http import JsonResponse
from django.views import View

from articles.models import Card


class HealthView(View):
    def get(self, request):
        return JsonResponse({"status": "ok"})


class CardListView(View):
    def get(self, request):
        cards = [
            {
                "uuid": str(c.uuid),
                "timeframe": c.timeframe,
                "period_start": c.period_start.isoformat(),
                "title": c.title,
                "importance_score": c.importance_score,
            }
            for c in Card.objects.all().order_by("-period_start")[:20]
        ]
        return JsonResponse({"cards": cards})


class CardDetailView(View):
    def get(self, request, pk):
        card = Card.objects.filter(pk=pk).first()
        if not card:
            return JsonResponse({"error": "not found"}, status=404)
        return JsonResponse(
            {
                "uuid": str(card.uuid),
                "timeframe": card.timeframe,
                "period_start": card.period_start.isoformat(),
                "period_end": card.period_end.isoformat(),
                "title": card.title,
                "summary": card.summary,
                "body": card.body,
                "importance_score": card.importance_score,
                "importance_reason": card.importance_reason,
                "assets": [
                    {"symbol": a.series.symbol, "label": a.label} for a in card.assets.all()
                ],
            }
        )
