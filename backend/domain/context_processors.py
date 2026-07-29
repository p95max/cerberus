from __future__ import annotations

from typing import Any

from accounts.roles import ROLE_ADMINISTRATOR, ROLE_MANAGER, has_role


def operator_permissions(request: Any) -> dict[str, bool]:
    return {
        "can_manage_configuration": has_role(
            request.user,
            (ROLE_ADMINISTRATOR, ROLE_MANAGER),
        )
    }
