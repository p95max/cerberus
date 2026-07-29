from __future__ import annotations

import os

from django.conf import settings
from django.contrib.auth.models import Group
from django.core.management.base import BaseCommand

from accounts.models import User
from accounts.roles import ROLE_ADMINISTRATOR, ROLE_OPERATOR, ensure_role_groups


class Command(BaseCommand):
    help = "Create local development operator and administrator accounts when enabled."

    def handle(self, *args: object, **options: object) -> None:
        operator_enabled = os.getenv("CREATE_TEST_OPERATOR", "false").lower() in {
            "1",
            "true",
            "yes",
        }
        admin_enabled = os.getenv("CREATE_TEST_ADMIN", "false").lower() in {"1", "true", "yes"}
        if not settings.DEBUG or not (operator_enabled or admin_enabled):
            self.stdout.write("Test user creation skipped.")
            return

        ensure_role_groups()
        if operator_enabled:
            self.ensure_user(
                username=os.getenv("TEST_OPERATOR_USERNAME", "operator"),
                password=os.getenv("TEST_OPERATOR_PASSWORD", "operator-demo-password"),
                role=ROLE_OPERATOR,
                label="operator",
            )
        if admin_enabled:
            self.ensure_user(
                username=os.getenv("TEST_ADMIN_USERNAME", "admin"),
                password=os.getenv("TEST_ADMIN_PASSWORD", "admin-demo-password"),
                role=ROLE_ADMINISTRATOR,
                label="administrator",
            )

    def ensure_user(self, *, username: str, password: str, role: str, label: str) -> None:
        user, created = User.objects.get_or_create(
            username=username,
            defaults={"is_active": True},
        )
        role_group = Group.objects.get(name=role)
        role_assigned = not user.groups.filter(pk=role_group.pk).exists()
        user.groups.add(role_group)
        if created:
            user.set_password(password)
            user.save(update_fields=("password",))
            self.stdout.write(self.style.SUCCESS(f"Created test {label}: {username}"))
        else:
            self.stdout.write(f"Test {label} already exists: {username}")
        if role_assigned:
            self.stdout.write(self.style.SUCCESS(f"Assigned {role} role to: {username}"))
