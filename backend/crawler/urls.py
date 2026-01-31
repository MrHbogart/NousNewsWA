from django.urls import path

from crawler import views


urlpatterns = [
    path("crawler/status/", views.CrawlerStatusView.as_view(), name="crawler-status"),
    path("crawler/run/", views.CrawlerRunView.as_view(), name="crawler-run"),
    path("crawler/config/", views.CrawlerConfigView.as_view(), name="crawler-config"),
    path("crawler/seeds/", views.CrawlerSeedsView.as_view(), name="crawler-seeds"),
    path("crawler/logs/", views.CrawlerLogsView.as_view(), name="crawler-logs"),
    path("crawler/export.csv", views.CrawlerExportView.as_view(), name="crawler-export"),
]
