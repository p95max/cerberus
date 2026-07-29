from __future__ import annotations

from dataclasses import dataclass

from django.conf import settings

from domain.models import RecognitionRetentionPolicy


@dataclass(frozen=True)
class RetentionPolicy:
    image_metadata_enabled: bool
    image_metadata_days: int
    event_enabled: bool
    event_days: int
    aggregate_audit_enabled: bool
    aggregate_audit_days: int


def retention_policy_defaults() -> dict[str, bool | int]:
    return {
        "image_metadata_enabled": (
            settings.RECOGNITION_RETENTION_ENABLED
            and settings.RECOGNITION_IMAGE_METADATA_RETENTION_ENABLED
        ),
        "image_metadata_retention_days": settings.RECOGNITION_IMAGE_METADATA_RETENTION_DAYS,
        "event_retention_enabled": (
            settings.RECOGNITION_RETENTION_ENABLED and settings.RECOGNITION_EVENT_RETENTION_ENABLED
        ),
        "event_retention_days": settings.RECOGNITION_EVENT_RETENTION_DAYS,
        "aggregate_audit_retention_enabled": (
            settings.RECOGNITION_RETENTION_ENABLED
            and settings.RECOGNITION_AGGREGATE_AUDIT_RETENTION_ENABLED
        ),
        "aggregate_audit_retention_days": settings.RECOGNITION_AGGREGATE_AUDIT_RETENTION_DAYS,
    }


def get_retention_policy() -> RetentionPolicy:
    policy = RecognitionRetentionPolicy.objects.first()
    values = retention_policy_defaults() if policy is None else {
        "image_metadata_enabled": policy.image_metadata_enabled,
        "image_metadata_retention_days": policy.image_metadata_retention_days,
        "event_retention_enabled": policy.event_retention_enabled,
        "event_retention_days": policy.event_retention_days,
        "aggregate_audit_retention_enabled": policy.aggregate_audit_retention_enabled,
        "aggregate_audit_retention_days": policy.aggregate_audit_retention_days,
    }
    return RetentionPolicy(
        image_metadata_enabled=bool(values["image_metadata_enabled"]),
        image_metadata_days=int(values["image_metadata_retention_days"]),
        event_enabled=bool(values["event_retention_enabled"]),
        event_days=int(values["event_retention_days"]),
        aggregate_audit_enabled=bool(values["aggregate_audit_retention_enabled"]),
        aggregate_audit_days=int(values["aggregate_audit_retention_days"]),
    )
