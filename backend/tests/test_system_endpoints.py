import pytest
from django.conf import settings
from django.test import Client


@pytest.mark.django_db
def test_health_and_readiness_endpoints() -> None:
    client = Client()

    assert client.get("/healthz").json() == {"status": "ok"}
    assert client.get("/readyz").json() == {"status": "ready"}


def test_version_endpoint() -> None:
    response = Client().get("/version")

    assert response.status_code == 200
    assert response.json()["service"] == "cerberus-core"
    assert response.json()["version"] == settings.CERBERUS_VERSION


def test_openapi_schema_and_swagger_ui_are_available() -> None:
    client = Client()

    assert client.get("/api/schema/").status_code == 200
    assert client.get("/api/docs/").status_code == 200


def test_login_alias_redirects_to_the_operator_login() -> None:
    response = Client().get("/login/")

    assert response.status_code == 302
    assert response["Location"] == "/operator/login/"
