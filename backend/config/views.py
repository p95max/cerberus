from __future__ import annotations

from typing import Any

from django.conf import settings
from django.core.cache import cache
from django.db import connection
from django.http import JsonResponse
from django.views.decorators.http import require_GET


@require_GET
def health(request: Any) -> JsonResponse:
    """Report that the process can accept HTTP traffic."""
    return JsonResponse({"status": "ok"})


@require_GET
def readiness(request: Any) -> JsonResponse:
    """Verify the database and cache dependencies before accepting work."""
    try:
        connection.ensure_connection()
        cache.set("cerberus-readiness", "ok", timeout=5)
        if cache.get("cerberus-readiness") != "ok":
            raise RuntimeError("Cache readback failed")
    except Exception:
        return JsonResponse({"status": "unavailable"}, status=503)

    return JsonResponse({"status": "ready"})


@require_GET
def version(request: Any) -> JsonResponse:
    return JsonResponse(
        {
            "service": "cerberus-core",
            "version": settings.CERBERUS_VERSION,
            "environment": settings.CERBERUS_ENV,
        }
    )
