from __future__ import annotations

import os

from django.conf import settings
from django.contrib.auth.models import Group
from django.core.management.base import BaseCommand

from accounts.models import User
from accounts.roles import ROLE_OPERATOR, ensure_role_groups


class Command(BaseCommand):
    help = "Create the local development operator account when explicitly enabled."

    def handle(self, *args: object, **options: object) -> None:
        enabled = os.getenv("CREATE_TEST_OPERATOR", "false").lower() in {"1", "true", "yes"}
        if not settings.DEBUG or not enabled:
            self.stdout.write("Test operator creation skipped.")
            return

        username = os.getenv("TEST_OPERATOR_USERNAME", "operator")
        password = os.getenv("TEST_OPERATOR_PASSWORD", "operator-demo-password")
        ensure_role_groups()
        user, created = User.objects.get_or_create(
            username=username,
            defaults={"is_active": True},
        )
        user.groups.add(Group.objects.get(name=ROLE_OPERATOR))
        if created:
            user.set_password(password)
            user.save(update_fields=("password",))
            self.stdout.write(self.style.SUCCESS(f"Created test operator: {username}"))
        else:
            self.stdout.write(f"Test operator already exists: {username}")
