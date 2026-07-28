from __future__ import annotations

from django.contrib.auth.models import Group
from django.db.models.signals import post_migrate
from django.dispatch import receiver

ROLE_ADMINISTRATOR = "Administrator"
ROLE_MANAGER = "Manager"
ROLE_OPERATOR = "Operator"
ROLE_READ_ONLY = "Read-only"
ROLE_NAMES = (ROLE_ADMINISTRATOR, ROLE_MANAGER, ROLE_OPERATOR, ROLE_READ_ONLY)


def ensure_role_groups() -> None:
    for role_name in ROLE_NAMES:
        Group.objects.get_or_create(name=role_name)


def has_role(user: object, allowed_roles: tuple[str, ...]) -> bool:
    if not getattr(user, "is_authenticated", False):
        return False
    if getattr(user, "is_superuser", False):
        return True
    return user.groups.filter(name__in=allowed_roles).exists()


@receiver(post_migrate)
def create_role_groups(**_: object) -> None:
    ensure_role_groups()
