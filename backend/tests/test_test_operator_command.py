from __future__ import annotations

import pytest
from django.core.management import call_command
from django.test import Client, override_settings

from accounts.models import ServiceCredential, User
from accounts.roles import ROLE_MANAGER, ROLE_OPERATOR, ensure_role_groups
from domain.models import (
    AccessDecision,
    AccessList,
    AccessRule,
    Camera,
    Gate,
    ParkingSite,
    RecognitionEvent,
    Vehicle,
)


@pytest.mark.django_db
@override_settings(DEBUG=True)
def test_ensure_test_operator_is_idempotent(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CREATE_TEST_OPERATOR", "true")
    monkeypatch.setenv("CREATE_TEST_MANAGER", "false")
    monkeypatch.setenv("CREATE_TEST_ADMIN", "false")
    monkeypatch.setenv("TEST_OPERATOR_USERNAME", "test-operator")
    monkeypatch.setenv("TEST_OPERATOR_PASSWORD", "test-password")

    call_command("ensure_test_operator")
    call_command("ensure_test_operator")

    user = User.objects.get(username="test-operator")
    assert User.objects.filter(username="test-operator").count() == 1
    assert user.check_password("test-password")
    assert user.groups.filter(name=ROLE_OPERATOR).exists()


@pytest.mark.django_db
@override_settings(DEBUG=True)
def test_ensure_test_operator_assigns_role_to_existing_user(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ensure_role_groups()
    User.objects.create_user(username="existing-operator", password="password")
    monkeypatch.setenv("CREATE_TEST_OPERATOR", "true")
    monkeypatch.setenv("CREATE_TEST_MANAGER", "false")
    monkeypatch.setenv("CREATE_TEST_ADMIN", "false")
    monkeypatch.setenv("TEST_OPERATOR_USERNAME", "existing-operator")

    call_command("ensure_test_operator")

    user = User.objects.get(username="existing-operator")
    assert user.groups.filter(name=ROLE_OPERATOR).exists()


@pytest.mark.django_db
@override_settings(DEBUG=True)
def test_ensure_test_operator_creates_administrator(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CREATE_TEST_OPERATOR", "false")
    monkeypatch.setenv("CREATE_TEST_MANAGER", "false")
    monkeypatch.setenv("CREATE_TEST_ADMIN", "true")
    monkeypatch.setenv("TEST_ADMIN_USERNAME", "test-admin")
    monkeypatch.setenv("TEST_ADMIN_PASSWORD", "test-admin-password")

    call_command("ensure_test_operator")

    user = User.objects.get(username="test-admin")
    assert user.check_password("test-admin-password")
    assert user.groups.filter(name="Administrator").exists()
    assert user.is_staff
    assert user.is_superuser
    client = Client()
    client.force_login(user)
    assert client.get("/admin/").status_code == 200


@pytest.mark.django_db
@override_settings(DEBUG=True)
def test_ensure_test_operator_creates_manager(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CREATE_TEST_OPERATOR", "false")
    monkeypatch.setenv("CREATE_TEST_MANAGER", "true")
    monkeypatch.setenv("CREATE_TEST_ADMIN", "false")
    monkeypatch.setenv("TEST_MANAGER_USERNAME", "test-manager")
    monkeypatch.setenv("TEST_MANAGER_PASSWORD", "test-manager-password")

    call_command("ensure_test_operator")

    user = User.objects.get(username="test-manager")
    assert user.check_password("test-manager-password")
    assert user.groups.filter(name=ROLE_MANAGER).exists()


@pytest.mark.django_db
@override_settings(DEBUG=True)
def test_ensure_test_operator_creates_idempotent_demo_data(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CREATE_TEST_OPERATOR", "false")
    monkeypatch.setenv("CREATE_TEST_MANAGER", "false")
    monkeypatch.setenv("CREATE_TEST_ADMIN", "false")
    monkeypatch.setenv("CREATE_DEMO_DATA", "true")

    call_command("ensure_test_operator")
    call_command("ensure_test_operator")

    assert ParkingSite.objects.filter(external_id="demo-parking").count() == 1
    assert Gate.objects.filter(site__external_id="demo-parking").count() == 2
    assert Camera.objects.filter(external_id="demo-entry-camera").exists()
    assert Vehicle.objects.filter(normalized_plate="A123BC77").exists()
    assert RecognitionEvent.objects.filter(image_metadata__source="demo-seed").count() == 3
    credential = ServiceCredential.objects.get(client_id="janus-demo")
    assert credential.check_key("janus-demo-key")
    assert set(AccessDecision.objects.values_list("outcome", flat=True)) == {
        AccessDecision.Outcome.ALLOW,
        AccessDecision.Outcome.DENY,
        AccessDecision.Outcome.MANUAL_REVIEW,
    }


@pytest.mark.django_db
@override_settings(DEBUG=True)
def test_demo_seed_deactivates_conflicting_demo_rules(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CREATE_TEST_OPERATOR", "false")
    monkeypatch.setenv("CREATE_TEST_MANAGER", "false")
    monkeypatch.setenv("CREATE_TEST_ADMIN", "false")
    monkeypatch.setenv("CREATE_DEMO_DATA", "true")

    call_command("ensure_test_operator")
    allow_vehicle = Vehicle.objects.get(normalized_plate="A123BC77")
    blacklist = AccessList.objects.get(name="Demo blacklist")
    gate = Gate.objects.get(external_id="demo-entry")
    conflicting_rule = AccessRule.objects.create(
        access_list=blacklist,
        vehicle=allow_vehicle,
        gate=gate,
        decision=AccessRule.Decision.DENY,
        priority=0,
    )

    call_command("ensure_test_operator")

    conflicting_rule.refresh_from_db()
    assert not conflicting_rule.is_active
