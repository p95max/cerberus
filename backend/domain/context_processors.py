from __future__ import annotations

from typing import Any

from django.conf import settings
from accounts.roles import (
    ROLE_ADMINISTRATOR,
    ROLE_MANAGER,
    ROLE_OPERATOR,
    ROLE_READ_ONLY,
    has_role,
)
from domain.models import AccessDecision, BarrierCommand


def operator_permissions(request: Any) -> dict[str, Any]:
    role = None
    for candidate in (ROLE_ADMINISTRATOR, ROLE_MANAGER, ROLE_OPERATOR, ROLE_READ_ONLY):
        if has_role(request.user, (candidate,)):
            role = candidate
            break
    persistent_open_barriers = (
        list(
            BarrierCommand.objects.filter(
                status__in=(
                    BarrierCommand.Status.PENDING,
                    BarrierCommand.Status.SENT,
                    BarrierCommand.Status.ACKNOWLEDGED,
                ),
                auto_close_at__isnull=True,
            ).select_related("gate__site")
        )
        if settings.MOCK_BARRIER_CONTROL_ENABLED and request.user.is_authenticated
        else []
    )
    return {
        "can_manage_configuration": has_role(
            request.user,
            (ROLE_ADMINISTRATOR, ROLE_MANAGER),
        ),
        "can_view_configuration": has_role(
            request.user,
            (ROLE_ADMINISTRATOR, ROLE_MANAGER, ROLE_OPERATOR, ROLE_READ_ONLY),
        ),
        "can_view_activity_log": has_role(
            request.user,
            (ROLE_ADMINISTRATOR, ROLE_MANAGER),
        ),
        "can_control_barrier": settings.MOCK_BARRIER_CONTROL_ENABLED and has_role(
            request.user,
            (ROLE_ADMINISTRATOR, ROLE_MANAGER, ROLE_OPERATOR),
        ),
        "can_submit_demo_event": settings.DEMO_EVENT_SUBMISSION_ENABLED
        and has_role(request.user, (ROLE_ADMINISTRATOR, ROLE_MANAGER)),
        "current_operator_role": role,
        "manual_review_count": (
            AccessDecision.objects.filter(
                outcome=AccessDecision.Outcome.MANUAL_REVIEW,
                manual_review_closed_at__isnull=True,
            ).count()
            if request.user.is_authenticated
            else 0
        ),
        "persistent_open_barriers": persistent_open_barriers,
    }
