from __future__ import annotations

from typing import Any

from accounts.roles import (
    ROLE_ADMINISTRATOR,
    ROLE_MANAGER,
    ROLE_OPERATOR,
    ROLE_READ_ONLY,
    has_role,
)
from domain.models import AccessDecision


def operator_permissions(request: Any) -> dict[str, Any]:
    role = None
    for candidate in (ROLE_ADMINISTRATOR, ROLE_MANAGER, ROLE_OPERATOR, ROLE_READ_ONLY):
        if has_role(request.user, (candidate,)):
            role = candidate
            break
    return {
        "can_manage_configuration": has_role(
            request.user,
            (ROLE_ADMINISTRATOR, ROLE_MANAGER),
        ),
        "can_view_configuration": has_role(
            request.user,
            (ROLE_ADMINISTRATOR, ROLE_MANAGER, ROLE_OPERATOR, ROLE_READ_ONLY),
        ),
        "current_operator_role": role,
        "manual_review_count": (
            AccessDecision.objects.filter(outcome=AccessDecision.Outcome.MANUAL_REVIEW).count()
            if request.user.is_authenticated
            else 0
        ),
    }
