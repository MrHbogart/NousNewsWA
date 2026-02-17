from django.urls import path

from articles.views import (
    ArticleDetailView,
    BriefListView,
    HealthView,
    Last24HoursView,
    LastHourView,
)

urlpatterns = [
    path("health/", HealthView.as_view(), name="health"),
    path("last24h/", Last24HoursView.as_view(), name="last-24-hours"),
    path("lasthour/", LastHourView.as_view(), name="last-hour"),
    path("briefs/", BriefListView.as_view(), name="briefs"),
    path("articles/<str:pk>/", ArticleDetailView.as_view(), name="article-detail"),
]
