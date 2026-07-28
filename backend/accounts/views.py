from __future__ import annotations

import hashlib
from typing import Any

from django.conf import settings
from django.contrib.auth import authenticate, login, logout
from django.core.cache import cache
from django.http import HttpRequest
from rest_framework import exceptions, status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from accounts.audit import client_ip, record_audit
from accounts.models import AuditLog
from accounts.permissions import HasManagementRole, IsAdministrator
from accounts.roles import ROLE_NAMES, has_role
from accounts.serializers import AuditLogSerializer, LoginSerializer


def login_attempt_key(request: HttpRequest, username: str) -> str:
    identity = f"{client_ip(request) or 'unknown'}:{username.casefold()}"
    return f"login-failures:{hashlib.sha256(identity.encode()).hexdigest()}"


class LoginAPIView(APIView):
    authentication_classes: list[type[Any]] = []
    permission_classes = [AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "login"

    def post(self, request: HttpRequest) -> Response:
        serializer = LoginSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        username = serializer.validated_data["username"]
        attempt_key = login_attempt_key(request, username)
        if cache.get(attempt_key, 0) >= settings.LOGIN_MAX_FAILURES:
            record_audit("login_locked", request=request, details={"username": username})
            raise exceptions.Throttled(wait=settings.LOGIN_LOCKOUT_SECONDS)

        user = authenticate(
            request, username=username, password=serializer.validated_data["password"]
        )
        if user is None or not has_role(user, ROLE_NAMES):
            cache.set(
                attempt_key,
                cache.get(attempt_key, 0) + 1,
                timeout=settings.LOGIN_LOCKOUT_SECONDS,
            )
            record_audit("login_failed", request=request, details={"username": username})
            raise exceptions.AuthenticationFailed("Invalid credentials.")

        cache.delete(attempt_key)
        login(request, user)
        record_audit("login_succeeded", request=request, actor=user)
        return Response(
            {"username": user.username, "roles": list(user.groups.values_list("name", flat=True))}
        )


class LogoutAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request: HttpRequest) -> Response:
        record_audit("logout", request=request, actor=request.user)
        logout(request)
        return Response(status=status.HTTP_204_NO_CONTENT)


class AuditedPermissionAPIView(APIView):
    def permission_denied(
        self, request: HttpRequest, message: str | None = None, code: str | None = None
    ) -> None:
        actor = request.user if request.user.is_authenticated else None
        record_audit(
            "permission_denied", request=request, actor=actor, details={"path": request.path}
        )
        super().permission_denied(request, message=message, code=code)


class RoleManagementAPIView(AuditedPermissionAPIView):
    permission_classes = [IsAdministrator]

    def get(self, request: HttpRequest) -> Response:
        return Response({"roles": ROLE_NAMES})


class AuditLogAPIView(AuditedPermissionAPIView):
    permission_classes = [HasManagementRole]

    def get(self, request: HttpRequest) -> Response:
        return Response(AuditLogSerializer(AuditLog.objects.all()[:100], many=True).data)


class ServiceIdentityAPIView(AuditedPermissionAPIView):
    permission_classes = [IsAuthenticated]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "service"

    def get(self, request: HttpRequest) -> Response:
        if request.auth is None:
            raise exceptions.NotAuthenticated("A service API key is required.")
        return Response({"client_id": request.auth.client_id, "username": request.user.username})
