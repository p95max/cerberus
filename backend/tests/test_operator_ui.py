from __future__ import annotations

from decimal import Decimal

import pytest
from django.contrib.auth.models import Group
from django.test import Client
from django.utils import timezone

from accounts.models import AuditLog, User
from accounts.roles import ROLE_MANAGER, ROLE_OPERATOR, ensure_role_groups
from domain.models import AccessDecision, Camera, Gate, ParkingSite, RecognitionEvent


@pytest.fixture
def operator() -> User:
    ensure_role_groups()
    user = User.objects.create_user(username="operator-ui", password="password")
    user.groups.add(Group.objects.get(name=ROLE_OPERATOR))
    return user


@pytest.fixture
def manager() -> User:
    ensure_role_groups()
    user = User.objects.create_user(username="manager-ui", password="password")
    user.groups.add(Group.objects.get(name=ROLE_MANAGER))
    return user


@pytest.fixture
def manual_review_event() -> RecognitionEvent:
    site = ParkingSite.objects.create(external_id="ui-site", name="UI Site")
    gate = Gate.objects.create(site=site, external_id="ui-gate", name="UI Gate", direction="entry")
    camera = Camera.objects.create(gate=gate, external_id="ui-camera", name="UI Camera")
    event = RecognitionEvent.objects.create(
        camera=camera,
        normalized_plate="A123BC77",
        confidence=Decimal("0.9000"),
        captured_at=timezone.now(),
    )
    AccessDecision.objects.create(
        event=event,
        outcome=AccessDecision.Outcome.MANUAL_REVIEW,
        reason="No matching access rule.",
    )
    AuditLog.objects.create(action="recognition_event_received", details={"event_id": event.pk})
    return event


@pytest.mark.django_db
def test_operator_dashboard_shows_events_status_and_filters(
    operator: User, manual_review_event: RecognitionEvent
) -> None:
    client = Client()
    client.force_login(operator)

    response = client.get("/operator/", {"plate": "A 123"})

    assert response.status_code == 200
    assert b"A123BC77" in response.content
    assert b"Manual review" in response.content
    assert b"Apply filters" in response.content
    assert b'aria-current="page">Events' in response.content
    assert b"events awaiting manual review">1<" in response.content


@pytest.mark.django_db
def test_event_detail_exposes_reason_audit_and_confirmed_manual_command(
    operator: User, manual_review_event: RecognitionEvent
) -> None:
    client = Client()
    client.force_login(operator)
    detail = client.get(f"/operator/events/{manual_review_event.pk}/")
    rejected = client.post(f"/operator/events/{manual_review_event.pk}/", {"action": "close"})
    accepted = client.post(f"/operator/events/{manual_review_event.pk}/", {"action": "open"})

    assert detail.status_code == 200
    assert b"No matching access rule." in detail.content
    assert b"recognition_event_received" in detail.content
    assert rejected.status_code == 302
    assert accepted.status_code == 302
    assert manual_review_event.decision.barrier_commands.count() == 1
    assert AuditLog.objects.filter(action="manual_barrier_command_requested").exists()


@pytest.mark.django_db
def test_management_pages_require_manager_role(
    operator: User, manager: User, manual_review_event: RecognitionEvent
) -> None:
    client = Client()
    client.force_login(operator)
    assert client.get("/operator/manage/vehicles/").status_code == 403

    client.force_login(manager)
    response = client.get("/operator/manage/vehicles/")
    assert response.status_code == 200
    assert b"Vehicles" in response.content
