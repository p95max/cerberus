from __future__ import annotations

from typing import Any

from accounts.roles import (
    ROLE_ADMINISTRATOR,
    ROLE_MANAGER,
    ROLE_OPERATOR,
    ROLE_READ_ONLY,
    has_role,
)


def operator_permissions(request: Any) -> dict[str, bool]:
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
        "current_operator_role": role,
    }
