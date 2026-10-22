from django.urls import path

from prices.views import HealthView, MarketOverviewView, SeriesLatestView, SeriesListView

urlpatterns = [
    path("health/", HealthView.as_view(), name="prices-health"),
    path("overview/", MarketOverviewView.as_view(), name="market-overview"),
    path("series/", SeriesListView.as_view(), name="series-list"),
    path("series/<str:symbol>/latest/", SeriesLatestView.as_view(), name="series-latest"),
]
