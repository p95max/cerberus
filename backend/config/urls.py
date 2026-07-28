from django.urls import path
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView

from config.views import health, readiness, version

urlpatterns = [
    path("healthz", health, name="health"),
    path("readyz", readiness, name="readiness"),
    path("version", version, name="version"),
    path("api/schema/", SpectacularAPIView.as_view(), name="openapi-schema"),
    path("api/docs/", SpectacularSwaggerView.as_view(url_name="openapi-schema"), name="swagger-ui"),
]
