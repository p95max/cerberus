import pytest
from django.contrib.auth.models import Group
from django.test import Client

from accounts.models import AuditLog, ServiceCredential, User
from accounts.roles import ROLE_OPERATOR, ensure_role_groups


@pytest.fixture
def operator() -> User:
    ensure_role_groups()
    user = User.objects.create_user(username="operator", password="correct-horse-battery-staple")
    user.groups.add(Group.objects.get(name=ROLE_OPERATOR))
    return user


@pytest.mark.django_db
def test_operator_can_login_and_logout(operator: User) -> None:
    client = Client()

    response = client.post(
        "/api/v1/auth/login",
        data={"username": operator.username, "password": "correct-horse-battery-staple"},
        content_type="application/json",
    )

    assert response.status_code == 200
    assert ROLE_OPERATOR in response.json()["roles"]
    assert client.post("/api/v1/auth/logout").status_code == 204
    assert AuditLog.objects.filter(action="login_succeeded", actor=operator).exists()


@pytest.mark.django_db
def test_management_and_audit_routes_require_roles(operator: User) -> None:
    client = Client()
    client.force_login(operator)

    assert client.get("/api/v1/management/roles").status_code == 403
    assert client.get("/api/v1/audit-logs").status_code == 403
    assert AuditLog.objects.filter(action="permission_denied", actor=operator).count() == 2


@pytest.mark.django_db
def test_service_key_authentication(operator: User) -> None:
    credential = ServiceCredential(client_id="janus", user=operator)
    credential.set_key("test-service-key")
    credential.save()

    response = Client().get(
        "/api/v1/service/whoami",
        headers={"X-Service-Client": "janus", "X-Service-Key": "test-service-key"},
    )

    assert response.status_code == 200
    assert response.json()["client_id"] == "janus"


@pytest.mark.django_db
def test_failed_login_is_audited() -> None:
    response = Client().post(
        "/api/v1/auth/login",
        data={"username": "unknown", "password": "wrong"},
        content_type="application/json",
    )

    assert response.status_code == 403
    assert AuditLog.objects.filter(action="login_failed").exists()
