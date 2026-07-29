from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

import pytest
from django.utils import timezone

from accounts.models import AuditLog
from domain.models import (
    AccessDecision,
    BarrierCommand,
    Camera,
    Gate,
    ParkingSite,
    RecognitionEvent,
    RecognitionRetentionPolicy,
)
from domain.tasks import purge_expired_recognition_events


@pytest.mark.django_db
def test_retention_task_applies_each_enabled_level() -> None:
    now = timezone.now()
    site = ParkingSite.objects.create(external_id="retention-site", name="Retention Site")
    gate = Gate.objects.create(
        site=site,
        external_id="retention-gate",
        name="Retention Gate",
        direction=Gate.Direction.ENTRY,
    )
    camera = Camera.objects.create(
        gate=gate,
        external_id="retention-camera",
        name="Retention Camera",
    )
    expired_event = RecognitionEvent.objects.create(
        camera=camera,
        normalized_plate="EXPIRED1",
        confidence=Decimal("0.9000"),
        captured_at=now - timedelta(days=181),
        retention_expires_at=now - timedelta(days=1),
    )
    decision = AccessDecision.objects.create(
        event=expired_event,
        outcome=AccessDecision.Outcome.MANUAL_REVIEW,
        reason="Expired test event.",
    )
    command = BarrierCommand.objects.create(decision=decision, gate=gate)
    metadata_event = RecognitionEvent.objects.create(
        camera=camera,
        normalized_plate="METADATA1",
        confidence=Decimal("0.9000"),
        captured_at=now - timedelta(days=31),
        image_metadata={"object_key": "recognition/METADATA1.jpg"},
        retention_expires_at=now + timedelta(days=149),
    )
    old_aggregate_audit = AuditLog.objects.create(action="recognition_events_purged")
    AuditLog.objects.filter(pk=old_aggregate_audit.pk).update(created_at=now - timedelta(days=731))
    RecognitionRetentionPolicy.objects.create(
        pk=1,
        image_metadata_enabled=True,
        image_metadata_retention_days=30,
        event_retention_enabled=True,
        event_retention_days=180,
        aggregate_audit_retention_enabled=True,
        aggregate_audit_retention_days=730,
    )

    result = purge_expired_recognition_events.run()

    assert result == {
        "purged_events": 1,
        "purged_metadata": 1,
        "purged_aggregate_audits": 1,
    }
    assert not RecognitionEvent.objects.filter(pk=expired_event.pk).exists()
    assert not AccessDecision.objects.filter(pk=decision.pk).exists()
    assert not BarrierCommand.objects.filter(pk=command.pk).exists()
    metadata_event.refresh_from_db()
    assert metadata_event.image_metadata == {}
    assert not AuditLog.objects.filter(pk=old_aggregate_audit.pk).exists()


@pytest.mark.django_db
def test_retention_task_respects_disabled_levels() -> None:
    now = timezone.now()
    site = ParkingSite.objects.create(external_id="retention-disabled-site", name="Disabled Site")
    gate = Gate.objects.create(
        site=site,
        external_id="retention-disabled-gate",
        name="Disabled Gate",
        direction=Gate.Direction.ENTRY,
    )
    camera = Camera.objects.create(
        gate=gate,
        external_id="retention-disabled-camera",
        name="Disabled Camera",
    )
    event = RecognitionEvent.objects.create(
        camera=camera,
        normalized_plate="KEEPME1",
        confidence=Decimal("0.9000"),
        captured_at=now - timedelta(days=365),
        image_metadata={"object_key": "recognition/KEEPME1.jpg"},
        retention_expires_at=now - timedelta(days=1),
    )
    RecognitionRetentionPolicy.objects.create(
        pk=1,
        image_metadata_enabled=False,
        event_retention_enabled=False,
        aggregate_audit_retention_enabled=False,
    )

    result = purge_expired_recognition_events.run()

    assert result == {
        "purged_events": 0,
        "purged_metadata": 0,
        "purged_aggregate_audits": 0,
    }
    event.refresh_from_db()
    assert event.image_metadata == {"object_key": "recognition/KEEPME1.jpg"}
