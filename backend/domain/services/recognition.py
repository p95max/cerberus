from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from django.db import IntegrityError, transaction
from rest_framework import serializers

from domain.models import AccessDecision, Camera, RecognitionEvent
from domain.services.decisions import decide, normalize_plate


@dataclass(frozen=True)
class RecognitionSubmission:
    event: RecognitionEvent
    decision: AccessDecision
    created: bool


def _find_camera(external_id: str, direction: str) -> Camera:
    try:
        camera = Camera.objects.select_related("gate").get(
            external_id=external_id,
            is_active=True,
            gate__is_active=True,
        )
    except Camera.DoesNotExist as error:
        raise serializers.ValidationError(
            {"camera_external_id": "Unknown active camera."}
        ) from error

    if camera.gate.direction != direction:
        raise serializers.ValidationError(
            {"direction": "Direction does not match the camera gate."}
        )
    return camera


def _submission_for_existing(event: RecognitionEvent) -> RecognitionSubmission:
    return RecognitionSubmission(event=event, decision=decide(event), created=False)


@transaction.atomic
def submit_recognition_event(
    *,
    recognition_request_id: UUID,
    plate_number: str,
    confidence: Any,
    camera_external_id: str,
    direction: str,
    captured_at: datetime,
    image_metadata: dict[str, Any],
    submitted_by: Any,
) -> RecognitionSubmission:
    """Create exactly one event for a recognition request and decide it in Core."""
    existing = (
        RecognitionEvent.objects.select_related("decision")
        .filter(recognition_request_id=recognition_request_id)
        .first()
    )
    if existing is not None:
        return _submission_for_existing(existing)

    camera = _find_camera(camera_external_id, direction)
    try:
        with transaction.atomic():
            event = RecognitionEvent.objects.create(
                recognition_request_id=recognition_request_id,
                camera=camera,
                normalized_plate=normalize_plate(plate_number),
                confidence=confidence,
                captured_at=captured_at,
                image_metadata=image_metadata,
                submitted_by=submitted_by,
            )
            return RecognitionSubmission(event=event, decision=decide(event), created=True)
    except IntegrityError:
        event = RecognitionEvent.objects.select_related("decision").get(
            recognition_request_id=recognition_request_id
        )
        return _submission_for_existing(event)
