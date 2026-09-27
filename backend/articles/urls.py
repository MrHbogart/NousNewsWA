from django.urls import path

from articles.stream import article_stream, home_stream

from articles.views import (
    ArticleDetailView,
    BriefListView,
    HealthView,
    LastHourView,
)

urlpatterns = [
    path("health/", HealthView.as_view(), name="health"),
    path("lasthour/", LastHourView.as_view(), name="last-hour"),
    path("briefs/", BriefListView.as_view(), name="briefs"),
    path("articles/<str:pk>/", ArticleDetailView.as_view(), name="article-detail"),
    path("stream/home/", home_stream, name="stream-home"),
    path("stream/articles/<str:pk>/", article_stream, name="stream-article"),
]
