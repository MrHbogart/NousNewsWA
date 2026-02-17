from django.urls import path

from prices.views import SeriesListView, SeriesLatestView, HealthView

urlpatterns = [
    path("health/", HealthView.as_view(), name="prices-health"),
    path("series/", SeriesListView.as_view(), name="series-list"),
    path("series/<str:symbol>/latest/", SeriesLatestView.as_view(), name="series-latest"),
]
