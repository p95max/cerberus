from __future__ import annotations

from datetime import timedelta
from typing import Any

from celery import shared_task
from django.conf import settings
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from accounts.models import AuditLog
from domain.models import AccessDecision, BarrierCommand, RecognitionEvent
from domain.services.barrier import BarrierControllerError, get_barrier_controller
from domain.services.retention import get_retention_policy

AGGREGATE_RETENTION_AUDIT_ACTIONS = (
    "recognition_event_metadata_purged",
    "recognition_events_purged",
)


def barrier_command_audit_details(command: BarrierCommand) -> dict[str, Any]:
    details: dict[str, Any] = {
        "command_id": command.pk,
        "gate_id": command.gate_id,
        "gate_name": str(command.gate),
    }
    if command.decision_id:
        details["event_id"] = command.decision.event_id
    if command.request_reference:
        details["request_reference"] = command.request_reference
    return details


@shared_task
def dispatch_barrier_command(command_id: int) -> dict[str, Any]:
    """Send one command to the controller and schedule bounded retries on failure."""
    with transaction.atomic():
        command = (
            BarrierCommand.objects.select_for_update()
            .select_related("decision", "gate")
            .get(pk=command_id)
        )
        if command.status not in {BarrierCommand.Status.PENDING, BarrierCommand.Status.SENT}:
            return {"command_id": command.pk, "status": command.status}

        command.attempt_count += 1
        command.status = BarrierCommand.Status.SENT
        command.retry_after = None
        command.save(update_fields=("attempt_count", "status", "retry_after", "updated_at"))

        try:
            result = get_barrier_controller().open(
                command,
                timeout_seconds=settings.BARRIER_CONTROLLER_TIMEOUT_SECONDS,
            )
        except BarrierControllerError as error:
            command.last_error = str(error)
            if command.attempt_count < settings.BARRIER_COMMAND_MAX_RETRIES:
                command.status = BarrierCommand.Status.PENDING
                command.retry_after = timezone.now() + timedelta(
                    seconds=settings.BARRIER_COMMAND_RETRY_DELAY_SECONDS
                )
                command.save(
                    update_fields=("status", "retry_after", "last_error", "updated_at")
                )
                AuditLog.objects.create(
                    action="barrier_command_retry_scheduled",
                    details=barrier_command_audit_details(command),
                )
                if not settings.CELERY_TASK_ALWAYS_EAGER:
                    dispatch_barrier_command.apply_async(
                        args=[command.pk],
                        eta=command.retry_after,
                    )
                return {"command_id": command.pk, "status": command.status}

            command.status = BarrierCommand.Status.FAILED
            command.retry_after = None
            command.save(update_fields=("status", "retry_after", "last_error", "updated_at"))
            AuditLog.objects.create(
                action="barrier_command_failed",
                details=barrier_command_audit_details(command),
            )
            return {"command_id": command.pk, "status": command.status}

        if not result.acknowledged:
            raise RuntimeError("Barrier controller did not acknowledge the command.")
        command.status = BarrierCommand.Status.ACKNOWLEDGED
        command.last_error = ""
        command.save(update_fields=("status", "last_error", "updated_at"))
        AuditLog.objects.create(
            action="barrier_command_acknowledged",
            details=barrier_command_audit_details(command),
        )
        if command.auto_close_at is not None:
            close_barrier_after_delay.apply_async(args=[command.pk], eta=command.auto_close_at)
    return {"command_id": command.pk, "status": command.status}


@shared_task
def close_barrier_after_delay(command_id: int) -> dict[str, Any]:
    """Mark a mock barrier command closed and leave an auditable event history."""
    with transaction.atomic():
        command = (
            BarrierCommand.objects.select_for_update().select_related("decision", "gate").get(pk=command_id)
        )
        if command.closed_at is not None or command.status != BarrierCommand.Status.ACKNOWLEDGED:
            return {"command_id": command.pk, "status": command.status}

        command.status = BarrierCommand.Status.CLOSED
        command.closed_at = timezone.now()
        command.save(update_fields=("status", "closed_at", "updated_at"))
        AuditLog.objects.create(
            action="barrier_closed_automatically",
            details=barrier_command_audit_details(command),
        )
    return {"command_id": command.pk, "status": command.status}


@shared_task
def close_due_barrier_commands() -> dict[str, int]:
    """Reconcile auto-close commands in case an ETA task was lost during a worker restart."""
    command_ids = list(
        BarrierCommand.objects.filter(
            status=BarrierCommand.Status.ACKNOWLEDGED,
            auto_close_at__isnull=False,
            auto_close_at__lte=timezone.now(),
            closed_at__isnull=True,
        ).values_list("pk", flat=True)[:100]
    )
    for command_id in command_ids:
        close_barrier_after_delay.delay(command_id)
    return {"scheduled": len(command_ids)}


@shared_task
def purge_expired_recognition_events() -> dict[str, Any]:
    """Remove expired events and image metadata in bounded transactions."""
    now = timezone.now()
    policy = get_retention_policy()
    purged_metadata = 0
    if policy.image_metadata_enabled:
        metadata_cutoff = now - timedelta(days=policy.image_metadata_days)
        purged_metadata = (
            RecognitionEvent.objects.filter(
                captured_at__lte=metadata_cutoff,
            )
            .filter(Q(retention_expires_at__isnull=True) | Q(retention_expires_at__gt=now))
            .exclude(image_metadata={})
            .update(image_metadata={})
        )
    purged_events = 0

    if policy.event_enabled:
        event_cutoff = now - timedelta(days=policy.event_days)
        while True:
            event_ids = list(
                RecognitionEvent.objects.filter(
                    Q(retention_expires_at__lte=now)
                    | Q(retention_expires_at__isnull=True, captured_at__lte=event_cutoff)
                )
                .order_by("pk")
                .values_list("pk", flat=True)[: settings.RECOGNITION_PURGE_BATCH_SIZE]
            )
            if not event_ids:
                break

            with transaction.atomic():
                BarrierCommand.objects.filter(decision__event_id__in=event_ids).delete()
                AccessDecision.objects.filter(event_id__in=event_ids).delete()
                deleted_events, _ = RecognitionEvent.objects.filter(pk__in=event_ids).delete()
                purged_events += deleted_events

    if purged_metadata:
        AuditLog.objects.create(
            action="recognition_event_metadata_purged",
            details={
                "count": purged_metadata,
                "purged_before": (now - timedelta(days=policy.image_metadata_days)).isoformat(),
            },
        )
    if purged_events:
        AuditLog.objects.create(
            action="recognition_events_purged",
            details={"count": purged_events, "purged_before": now.isoformat()},
        )

    purged_aggregate_audits = 0
    if policy.aggregate_audit_enabled:
        audit_cutoff = now - timedelta(days=policy.aggregate_audit_days)
        purged_aggregate_audits, _ = AuditLog.objects.filter(
            action__in=AGGREGATE_RETENTION_AUDIT_ACTIONS,
            created_at__lte=audit_cutoff,
        ).delete()

    return {
        "purged_events": purged_events,
        "purged_metadata": purged_metadata,
        "purged_aggregate_audits": purged_aggregate_audits,
    }
