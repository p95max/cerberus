from __future__ import annotations

from django.conf import settings

from domain.models import BarrierControlSettings


def barrier_control_defaults() -> dict[str, int]:
    return {"auto_close_seconds": settings.BARRIER_AUTO_CLOSE_SECONDS}


def barrier_auto_close_seconds() -> int:
    configured = BarrierControlSettings.objects.first()
    if configured is None:
        return settings.BARRIER_AUTO_CLOSE_SECONDS
    return configured.auto_close_seconds
