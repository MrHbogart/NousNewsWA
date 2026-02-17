from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/", include("articles.urls")),
    path("api/", include("agent.urls")),
    path("api/prices/", include("prices.urls")),
    path("api/cards/", include("cards.urls")),
]
