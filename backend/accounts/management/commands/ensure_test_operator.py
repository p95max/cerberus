from __future__ import annotations

import os
from datetime import timedelta
from uuid import NAMESPACE_URL, uuid5

from django.conf import settings
from django.contrib.auth.models import Group
from django.core.management.base import BaseCommand
from django.utils import timezone

from accounts.models import ServiceCredential, User
from accounts.roles import (
    ROLE_ADMINISTRATOR,
    ROLE_MANAGER,
    ROLE_OPERATOR,
    ensure_role_groups,
)
from domain.models import (
    AccessList,
    AccessRule,
    Camera,
    Gate,
    ParkingSite,
    RecognitionEvent,
    Vehicle,
)
from domain.services.decisions import decide


class Command(BaseCommand):
    help = "Create local development users and demo parking data when enabled."

    def handle(self, *args: object, **options: object) -> None:
        operator_enabled = os.getenv("CREATE_TEST_OPERATOR", "false").lower() in {
            "1",
            "true",
            "yes",
        }
        manager_enabled = os.getenv("CREATE_TEST_MANAGER", "false").lower() in {
            "1",
            "true",
            "yes",
        }
        admin_enabled = os.getenv("CREATE_TEST_ADMIN", "false").lower() in {"1", "true", "yes"}
        demo_enabled = os.getenv("CREATE_DEMO_DATA", "false").lower() in {"1", "true", "yes"}
        if not settings.DEBUG or not (
            operator_enabled or manager_enabled or admin_enabled or demo_enabled
        ):
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
        if manager_enabled:
            self.ensure_user(
                username=os.getenv("TEST_MANAGER_USERNAME", "manager"),
                password=os.getenv("TEST_MANAGER_PASSWORD", "manager-demo-password"),
                role=ROLE_MANAGER,
                label="manager",
            )
        if admin_enabled:
            self.ensure_user(
                username=os.getenv("TEST_ADMIN_USERNAME", "admin"),
                password=os.getenv("TEST_ADMIN_PASSWORD", "admin-demo-password"),
                role=ROLE_ADMINISTRATOR,
                label="administrator",
                django_superuser=True,
            )
        if demo_enabled:
            self.seed_demo_data()
            self.ensure_demo_service_credential()

    def ensure_user(
        self,
        *,
        username: str,
        password: str,
        role: str,
        label: str,
        django_superuser: bool = False,
    ) -> None:
        user, created = User.objects.get_or_create(
            username=username,
            defaults={
                "is_active": True,
                "is_staff": django_superuser,
                "is_superuser": django_superuser,
            },
        )
        if django_superuser and not (user.is_staff and user.is_superuser):
            user.is_staff = True
            user.is_superuser = True
            user.save(update_fields=("is_staff", "is_superuser"))
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

    def seed_demo_data(self) -> None:
        site, _ = ParkingSite.objects.get_or_create(
            external_id="demo-parking",
            defaults={"name": "Demo Parking", "address": "100 Example Avenue"},
        )
        entry_gate, _ = Gate.objects.get_or_create(
            site=site,
            external_id="demo-entry",
            defaults={"name": "North Entry", "direction": Gate.Direction.ENTRY},
        )
        exit_gate, _ = Gate.objects.get_or_create(
            site=site,
            external_id="demo-exit",
            defaults={"name": "North Exit", "direction": Gate.Direction.EXIT},
        )
        entry_camera, _ = Camera.objects.get_or_create(
            external_id="demo-entry-camera",
            defaults={"gate": entry_gate, "name": "North Entry Camera"},
        )
        Camera.objects.get_or_create(
            external_id="demo-exit-camera",
            defaults={"gate": exit_gate, "name": "North Exit Camera"},
        )
        allowed_vehicle, _ = Vehicle.objects.get_or_create(
            normalized_plate="A123BC77",
            defaults={"display_plate": "A 123 BC 77", "owner_name": "Demo Allow"},
        )
        denied_vehicle, _ = Vehicle.objects.get_or_create(
            normalized_plate="B456DE77",
            defaults={"display_plate": "B 456 DE 77", "owner_name": "Demo Deny"},
        )
        whitelist, _ = AccessList.objects.get_or_create(
            site=site,
            name="Demo whitelist",
            defaults={"kind": AccessList.Kind.WHITELIST},
        )
        blacklist, _ = AccessList.objects.get_or_create(
            site=site,
            name="Demo blacklist",
            defaults={"kind": AccessList.Kind.BLACKLIST},
        )
        for access_list, kind in (
            (whitelist, AccessList.Kind.WHITELIST),
            (blacklist, AccessList.Kind.BLACKLIST),
        ):
            access_list.kind = kind
            access_list.is_active = True
            access_list.deleted_at = None
            access_list.save(update_fields=("kind", "is_active", "deleted_at", "updated_at"))

        def ensure_demo_rule(
            *, access_list: AccessList, vehicle: Vehicle, decision: str
        ) -> AccessRule:
            rule = (
                AccessRule.objects.filter(
                    access_list=access_list,
                    vehicle=vehicle,
                    gate=entry_gate,
                )
                .order_by("pk")
                .first()
            )
            if rule is None:
                return AccessRule.objects.create(
                    access_list=access_list,
                    vehicle=vehicle,
                    gate=entry_gate,
                    decision=decision,
                    priority=0,
                )
            rule.decision = decision
            rule.priority = 0
            rule.is_active = True
            rule.deleted_at = None
            rule.save(
                update_fields=(
                    "decision",
                    "priority",
                    "is_active",
                    "deleted_at",
                    "updated_at",
                )
            )
            return rule

        allow_rule = ensure_demo_rule(
            access_list=whitelist,
            vehicle=allowed_vehicle,
            decision=AccessRule.Decision.ALLOW,
        )
        deny_rule = ensure_demo_rule(
            access_list=blacklist,
            vehicle=denied_vehicle,
            decision=AccessRule.Decision.DENY,
        )
        AccessRule.objects.filter(access_list__in=(whitelist, blacklist)).exclude(
            pk__in=(allow_rule.pk, deny_rule.pk)
        ).update(is_active=False, deleted_at=timezone.now())
        captured_at = timezone.now()
        for key, plate, offset in (
            ("allow", "A123BC77", 2),
            ("deny", "B456DE77", 1),
            ("manual", "X000XX77", 0),
        ):
            event, _ = RecognitionEvent.objects.get_or_create(
                recognition_request_id=uuid5(NAMESPACE_URL, f"cerberus-demo-{key}"),
                defaults={
                    "camera": entry_camera,
                    "normalized_plate": plate,
                    "confidence": "0.9900",
                    "captured_at": captured_at - timedelta(minutes=offset),
                    "image_metadata": {"source": "demo-seed"},
                },
            )
            if not hasattr(event, "decision"):
                decide(event)
        self.stdout.write(self.style.SUCCESS("Demo parking data is ready."))

    def ensure_demo_service_credential(self) -> None:
        username = os.getenv("DEMO_SERVICE_USERNAME", "janus-demo")
        client_id = os.getenv("DEMO_SERVICE_CLIENT_ID", "janus-demo")
        raw_key = os.getenv("DEMO_SERVICE_KEY", "janus-demo-key")
        user, _ = User.objects.get_or_create(username=username, defaults={"is_active": True})
        credential, created = ServiceCredential.objects.get_or_create(
            client_id=client_id,
            defaults={"user": user, "is_active": True, "key_hash": ""},
        )
        if created:
            credential.set_key(raw_key)
            credential.save(update_fields=("key_hash",))
            self.stdout.write(self.style.SUCCESS(f"Created demo service credential: {client_id}"))
        else:
            self.stdout.write(f"Demo service credential already exists: {client_id}")
