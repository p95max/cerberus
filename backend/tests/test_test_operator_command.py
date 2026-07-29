from __future__ import annotations

import pytest
from django.core.management import call_command
from django.test import override_settings

from accounts.models import User
from accounts.roles import ROLE_OPERATOR


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
