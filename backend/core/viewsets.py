from rest_framework import viewsets
from rest_framework.permissions import SAFE_METHODS


class PublicReadModelViewSet(viewsets.ModelViewSet):
    public_field = "is_public"

    def get_queryset(self):
        queryset = super().get_queryset()
        if self.request.method in SAFE_METHODS and not self.request.user.is_staff:
            if self.public_field:
                return queryset.filter(**{self.public_field: True})
        return queryset
