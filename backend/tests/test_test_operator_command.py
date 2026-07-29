from __future__ import annotations

import pytest
from django.core.management import call_command
from django.test import override_settings

from accounts.models import User
from accounts.roles import ROLE_OPERATOR, ensure_role_groups


@pytest.mark.django_db
@override_settings(DEBUG=True)
def test_ensure_test_operator_is_idempotent(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CREATE_TEST_OPERATOR", "true")
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
    monkeypatch.setenv("TEST_OPERATOR_USERNAME", "existing-operator")

    call_command("ensure_test_operator")

    user = User.objects.get(username="existing-operator")
    assert user.groups.filter(name=ROLE_OPERATOR).exists()


@pytest.mark.django_db
@override_settings(DEBUG=True)
def test_ensure_test_operator_creates_administrator(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CREATE_TEST_OPERATOR", "false")
    monkeypatch.setenv("CREATE_TEST_ADMIN", "true")
    monkeypatch.setenv("TEST_ADMIN_USERNAME", "test-admin")
    monkeypatch.setenv("TEST_ADMIN_PASSWORD", "test-admin-password")

    call_command("ensure_test_operator")

    user = User.objects.get(username="test-admin")
    assert user.check_password("test-admin-password")
    assert user.groups.filter(name="Administrator").exists()
