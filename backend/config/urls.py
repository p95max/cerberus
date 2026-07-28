from django.urls import path
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView

from accounts.views import (
    AuditLogAPIView,
    LoginAPIView,
    LogoutAPIView,
    RoleManagementAPIView,
    ServiceIdentityAPIView,
)
from config.views import health, readiness, version

urlpatterns = [
    path("healthz", health, name="health"),
    path("readyz", readiness, name="readiness"),
    path("version", version, name="version"),
    path("api/schema/", SpectacularAPIView.as_view(), name="openapi-schema"),
    path("api/docs/", SpectacularSwaggerView.as_view(url_name="openapi-schema"), name="swagger-ui"),
    path("api/v1/auth/login", LoginAPIView.as_view(), name="login"),
    path("api/v1/auth/logout", LogoutAPIView.as_view(), name="logout"),
    path("api/v1/management/roles", RoleManagementAPIView.as_view(), name="role-management"),
    path("api/v1/audit-logs", AuditLogAPIView.as_view(), name="audit-logs"),
    path("api/v1/service/whoami", ServiceIdentityAPIView.as_view(), name="service-whoami"),
]
