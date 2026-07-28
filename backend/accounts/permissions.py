from __future__ import annotations

from rest_framework.permissions import BasePermission

from accounts.roles import ROLE_ADMINISTRATOR, ROLE_MANAGER, has_role


class HasManagementRole(BasePermission):
    message = "Administrator or Manager role is required."

    def has_permission(self, request: object, view: object) -> bool:
        return has_role(request.user, (ROLE_ADMINISTRATOR, ROLE_MANAGER))


class IsAdministrator(BasePermission):
    message = "Administrator role is required."

    def has_permission(self, request: object, view: object) -> bool:
        return has_role(request.user, (ROLE_ADMINISTRATOR,))
