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
from domain.operator_views import (
    ActivityLogView,
    EventDetailView,
    ManualReviewQueueView,
    OperatorDashboardView,
    OperatorLoginView,
    OperatorLogoutView,
    ResourceManagementView,
    ResourceUpdateView,
)
from domain.views import RecognitionEventAPIView

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
    path(
        "api/v1/recognition-events",
        RecognitionEventAPIView.as_view(),
        name="recognition-events",
    ),
    path("operator/login/", OperatorLoginView.as_view(), name="operator-login"),
    path("operator/logout/", OperatorLogoutView.as_view(), name="operator-logout"),
    path("operator/", OperatorDashboardView.as_view(), name="operator-dashboard"),
    path("operator/manual-review/", ManualReviewQueueView.as_view(), name="manual-review-queue"),
    path("operator/activity-log/", ActivityLogView.as_view(), name="operator-activity-log"),
    path("operator/events/<int:pk>/", EventDetailView.as_view(), name="operator-event-detail"),
    path(
        "operator/manage/<str:resource>/",
        ResourceManagementView.as_view(),
        name="manage-resource",
    ),
    path(
        "operator/manage/<str:resource>/<int:pk>/",
        ResourceUpdateView.as_view(),
        name="update-resource",
    ),
]
