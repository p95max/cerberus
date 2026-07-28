from __future__ import annotations

from typing import Any

from django.http import HttpRequest

from accounts.models import AuditLog, User


def client_ip(request: HttpRequest) -> str | None:
    forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR")
    if forwarded_for:
        return forwarded_for.split(",", maxsplit=1)[0].strip()
    return request.META.get("REMOTE_ADDR")


def record_audit(
    action: str,
    *,
    request: HttpRequest,
    actor: User | None = None,
    details: dict[str, Any] | None = None,
) -> AuditLog:
    return AuditLog.objects.create(
        action=action,
        actor=actor,
        ip_address=client_ip(request),
        details=details or {},
    )
