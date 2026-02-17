from django.urls import path

from cards.views import CardListView, CardDetailView, HealthView

urlpatterns = [
    path("health/", HealthView.as_view(), name="cards-health"),
    path("cards/", CardListView.as_view(), name="card-list"),
    path("cards/<uuid:pk>/", CardDetailView.as_view(), name="card-detail"),
]
