from __future__ import annotations

from uuid import uuid4

import pytest
from django.contrib.auth.models import Group
from django.test import Client
from django.utils import timezone

from accounts.models import AuditLog, ServiceCredential, User
from accounts.roles import ROLE_OPERATOR, ensure_role_groups
from domain.models import (
    AccessList,
    AccessRule,
    BarrierCommand,
    Camera,
    Gate,
    ParkingSite,
    RecognitionEvent,
    Vehicle,
)


@pytest.fixture
def janus_headers() -> dict[str, str]:
    ensure_role_groups()
    user = User.objects.create_user(username="janus-service", password="unused")
    user.groups.add(Group.objects.get(name=ROLE_OPERATOR))
    credential = ServiceCredential(client_id="janus", user=user)
    credential.set_key("janus-test-key")
    credential.save()
    return {"X-Service-Client": "janus", "X-Service-Key": "janus-test-key"}


@pytest.fixture
def camera() -> Camera:
    site = ParkingSite.objects.create(external_id="site-north", name="North site")
    gate = Gate.objects.create(
        site=site,
        external_id="north-entry",
        name="North entry",
        direction=Gate.Direction.ENTRY,
    )
    return Camera.objects.create(
        gate=gate,
        external_id="north-entry-camera",
        name="North entry camera",
    )


def payload(**changes: object) -> dict[str, object]:
    body: dict[str, object] = {
        "recognition_request_id": str(uuid4()),
        "plate_number": "A 123 BC 77",
        "confidence": "0.9900",
        "camera_external_id": "north-entry-camera",
        "direction": "entry",
        "captured_at": timezone.now().isoformat(),
        "image_metadata": {"frame_id": "frame-1", "mime_type": "image/jpeg"},
    }
    body.update(changes)
    return body


@pytest.mark.django_db
def test_service_can_submit_event_and_receive_core_decision(
    janus_headers: dict[str, str], camera: Camera
) -> None:
    response = Client().post(
        "/api/v1/recognition-events",
        data=payload(),
        content_type="application/json",
        headers=janus_headers,
    )

    assert response.status_code == 201
    assert response.json()["normalized_plate"] == "A123BC77"
    assert response.json()["decision"] == "manual_review"
    event = RecognitionEvent.objects.get(pk=response.json()["event_id"])
    assert event.image_metadata == {"frame_id": "frame-1", "mime_type": "image/jpeg"}
    assert event.camera == camera


@pytest.mark.django_db
def test_recognition_request_is_idempotent(janus_headers: dict[str, str], camera: Camera) -> None:
    request_id = str(uuid4())
    client = Client()
    first = client.post(
        "/api/v1/recognition-events",
        data=payload(recognition_request_id=request_id),
        content_type="application/json",
        headers=janus_headers,
    )
    second = client.post(
        "/api/v1/recognition-events",
        data=payload(recognition_request_id=request_id, plate_number="DIFFERENT"),
        content_type="application/json",
        headers=janus_headers,
    )

    assert first.status_code == 201
    assert second.status_code == 200
    assert second.json() == first.json()
    assert RecognitionEvent.objects.count() == 1


@pytest.mark.django_db
def test_rejects_invalid_direction_and_raw_image_data(
    janus_headers: dict[str, str], camera: Camera
) -> None:
    direction = Client().post(
        "/api/v1/recognition-events",
        data=payload(direction="exit"),
        content_type="application/json",
        headers=janus_headers,
    )
    raw_image = Client().post(
        "/api/v1/recognition-events",
        data=payload(image_metadata={"image_base64": "not-accepted"}),
        content_type="application/json",
        headers=janus_headers,
    )

    assert direction.status_code == 400
    assert "direction" in direction.json()
    assert raw_image.status_code == 400
    assert "image_metadata" in raw_image.json()


@pytest.mark.django_db
def test_rejects_oversized_request(janus_headers: dict[str, str], camera: Camera) -> None:
    response = Client().post(
        "/api/v1/recognition-events",
        data=payload(image_metadata={"note": "x" * 17000}),
        content_type="application/json",
        headers=janus_headers,
    )

    assert response.status_code == 400


@pytest.mark.django_db
def test_endpoint_requires_service_authentication(camera: Camera) -> None:
    response = Client().post(
        "/api/v1/recognition-events",
        data=payload(),
        content_type="application/json",
    )

    assert response.status_code == 403


@pytest.mark.django_db
def test_openapi_contains_recognition_event_contract() -> None:
    response = Client().get("/api/schema/", HTTP_ACCEPT="application/json")

    assert response.status_code == 200
    operation = response.json()["paths"]["/api/v1/recognition-events"]["post"]
    assert "RecognitionEventRequest" in str(operation)
    assert operation["responses"]["201"]


@pytest.mark.django_db
def test_end_to_end_demo_flow_covers_decisions_audit_and_manual_barrier_command(
    janus_headers: dict[str, str], camera: Camera
) -> None:
    allow_vehicle = Vehicle.objects.create(normalized_plate="A123BC77", display_plate="A 123 BC 77")
    deny_vehicle = Vehicle.objects.create(normalized_plate="B456DE77", display_plate="B 456 DE 77")
    whitelist = AccessList.objects.create(
        site=camera.gate.site, name="Demo allow", kind=AccessList.Kind.WHITELIST
    )
    blacklist = AccessList.objects.create(
        site=camera.gate.site, name="Demo deny", kind=AccessList.Kind.BLACKLIST
    )
    AccessRule.objects.create(
        access_list=whitelist,
        vehicle=allow_vehicle,
        gate=camera.gate,
        decision=AccessRule.Decision.ALLOW,
        priority=100,
    )
    AccessRule.objects.create(
        access_list=blacklist,
        vehicle=deny_vehicle,
        gate=camera.gate,
        decision=AccessRule.Decision.DENY,
        priority=100,
    )
    client = Client()
    results = {
        plate: client.post(
            "/api/v1/recognition-events",
            data=payload(plate_number=plate),
            content_type="application/json",
            headers=janus_headers,
        )
        for plate in ("A 123 BC 77", "B 456 DE 77", "X 000 XX 77")
    }

    assert {plate: response.json()["decision"] for plate, response in results.items()} == {
        "A 123 BC 77": "allow",
        "B 456 DE 77": "deny",
        "X 000 XX 77": "manual_review",
    }
    manual_event = RecognitionEvent.objects.get(pk=results["X 000 XX 77"].json()["event_id"])
    operator = User.objects.get(username="janus-service")
    client.force_login(operator)
    opened = client.post(
        f"/operator/events/{manual_event.pk}/",
        {"action": "open", "reason": "verified_visitor"},
    )

    assert opened.status_code == 302
    assert BarrierCommand.objects.filter(decision=manual_event.decision).exists()
    assert AuditLog.objects.filter(
        action="recognition_event_received", details__event_id=manual_event.pk
    ).exists()
    assert AuditLog.objects.filter(
        action="manual_barrier_command_requested", details__event_id=manual_event.pk
    ).exists()
