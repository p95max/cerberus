from __future__ import annotations

import uuid

from django.conf import settings
from django.db import models
from django.utils import timezone


class TimeStampedModel(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class SoftDeleteModel(TimeStampedModel):
    is_active = models.BooleanField(default=True)
    deleted_at = models.DateTimeField(blank=True, null=True)

    class Meta:
        abstract = True

    def deactivate(self) -> None:
        self.is_active = False
        self.deleted_at = timezone.now()
        self.save(update_fields=("is_active", "deleted_at", "updated_at"))


class ParkingSite(SoftDeleteModel):
    external_id = models.CharField(max_length=64, unique=True)
    name = models.CharField(max_length=120)
    address = models.CharField(max_length=255, blank=True)

    def __str__(self) -> str:
        return self.name


class Gate(SoftDeleteModel):
    class Direction(models.TextChoices):
        ENTRY = "entry", "Entry"
        EXIT = "exit", "Exit"

    site = models.ForeignKey(ParkingSite, on_delete=models.PROTECT, related_name="gates")
    external_id = models.CharField(max_length=64)
    name = models.CharField(max_length=120)
    direction = models.CharField(max_length=8, choices=Direction.choices)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=("site", "external_id"), name="unique_gate_external_id")
        ]

    def __str__(self) -> str:
        return f"{self.site.name} / {self.name}"


class Camera(SoftDeleteModel):
    gate = models.ForeignKey(Gate, on_delete=models.PROTECT, related_name="cameras")
    external_id = models.CharField(max_length=64, unique=True)
    name = models.CharField(max_length=120)

    def __str__(self) -> str:
        return self.name


class Vehicle(SoftDeleteModel):
    normalized_plate = models.CharField(max_length=32, unique=True)
    display_plate = models.CharField(max_length=32)
    owner_name = models.CharField(max_length=120, blank=True)

    def __str__(self) -> str:
        return self.display_plate


class AccessList(SoftDeleteModel):
    class Kind(models.TextChoices):
        WHITELIST = "whitelist", "Whitelist"
        BLACKLIST = "blacklist", "Blacklist"

    site = models.ForeignKey(ParkingSite, on_delete=models.PROTECT, related_name="access_lists")
    name = models.CharField(max_length=120)
    kind = models.CharField(max_length=16, choices=Kind.choices, default=Kind.WHITELIST)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=("site", "name"), name="unique_access_list_name")
        ]

    def __str__(self) -> str:
        return f"{self.site.name} / {self.name}"


class AccessRule(SoftDeleteModel):
    class Decision(models.TextChoices):
        ALLOW = "allow", "Allow"
        DENY = "deny", "Deny"
        MANUAL_REVIEW = "manual_review", "Manual review"

    access_list = models.ForeignKey(AccessList, on_delete=models.PROTECT, related_name="rules")
    vehicle = models.ForeignKey(Vehicle, on_delete=models.PROTECT, related_name="access_rules")
    gate = models.ForeignKey(
        Gate, blank=True, null=True, on_delete=models.PROTECT, related_name="access_rules"
    )
    decision = models.CharField(max_length=16, choices=Decision.choices)
    priority = models.PositiveSmallIntegerField(default=100)
    valid_from = models.DateTimeField(blank=True, null=True)
    valid_until = models.DateTimeField(blank=True, null=True)
    allowed_weekdays = models.JSONField(default=list, blank=True)
    allowed_from_time = models.TimeField(blank=True, null=True)
    allowed_until_time = models.TimeField(blank=True, null=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, blank=True, null=True, on_delete=models.SET_NULL
    )

    class Meta:
        indexes = [models.Index(fields=("vehicle", "is_active", "priority"))]

    def __str__(self) -> str:
        return f"{self.vehicle.display_plate}: {self.decision}"


class RecognitionEvent(TimeStampedModel):
    recognition_request_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    camera = models.ForeignKey(Camera, on_delete=models.PROTECT, related_name="recognition_events")
    normalized_plate = models.CharField(max_length=32)
    confidence = models.DecimalField(max_digits=5, decimal_places=4)
    captured_at = models.DateTimeField()
    image_metadata = models.JSONField(default=dict, blank=True)
    submitted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, blank=True, null=True, on_delete=models.SET_NULL
    )
    retention_expires_at = models.DateTimeField(blank=True, null=True)

    class Meta:
        indexes = [
            models.Index(fields=("camera", "captured_at")),
            models.Index(fields=("normalized_plate", "captured_at")),
            models.Index(fields=("retention_expires_at",), name="domain_retent_expires_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.normalized_plate} at {self.captured_at:%Y-%m-%d %H:%M:%S}"


class RecognitionRetentionPolicy(TimeStampedModel):
    """Singleton policy controlled from the operator configuration console."""

    image_metadata_enabled = models.BooleanField(default=True)
    image_metadata_retention_days = models.PositiveIntegerField(default=30)
    event_retention_enabled = models.BooleanField(default=True)
    event_retention_days = models.PositiveIntegerField(default=180)
    aggregate_audit_retention_enabled = models.BooleanField(default=True)
    aggregate_audit_retention_days = models.PositiveIntegerField(default=730)

    def __str__(self) -> str:
        return "Recognition data retention policy"


class AccessDecision(TimeStampedModel):
    class Outcome(models.TextChoices):
        ALLOW = "allow", "Allow"
        DENY = "deny", "Deny"
        MANUAL_REVIEW = "manual_review", "Manual review"

    event = models.OneToOneField(
        RecognitionEvent, on_delete=models.PROTECT, related_name="decision"
    )
    outcome = models.CharField(max_length=16, choices=Outcome.choices)
    reason = models.CharField(max_length=255)
    matched_rule = models.ForeignKey(AccessRule, blank=True, null=True, on_delete=models.PROTECT)
    decided_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, blank=True, null=True, on_delete=models.SET_NULL
    )

    def __str__(self) -> str:
        return f"{self.event.normalized_plate}: {self.outcome}"


class BarrierCommand(TimeStampedModel):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        SENT = "sent", "Sent"
        ACKNOWLEDGED = "acknowledged", "Acknowledged"
        FAILED = "failed", "Failed"
        EXPIRED = "expired", "Expired"
        CLOSED = "closed", "Closed"

    decision = models.ForeignKey(
        AccessDecision, on_delete=models.PROTECT, related_name="barrier_commands"
    )
    gate = models.ForeignKey(Gate, on_delete=models.PROTECT, related_name="barrier_commands")
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PENDING)
    idempotency_key = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    auto_close_at = models.DateTimeField(blank=True, null=True)
    closed_at = models.DateTimeField(blank=True, null=True)
    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, blank=True, null=True, on_delete=models.SET_NULL
    )

    def __str__(self) -> str:
        return f"{self.gate.name}: {self.status}"


class OperatorProfile(TimeStampedModel):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="operator_profile"
    )
    display_name = models.CharField(max_length=120)
    is_on_duty = models.BooleanField(default=False)
