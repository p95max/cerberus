from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime

from django.db import transaction
from django.db.models import Q, QuerySet
from django.utils import timezone

from domain.models import AccessDecision, AccessRule, RecognitionEvent


def normalize_plate(value: str) -> str:
    """Canonicalize a plate before every lookup; separators and case never matter."""
    return re.sub(r"[^A-Z0-9]", "", value.upper())


@dataclass(frozen=True)
class DecisionResult:
    outcome: str
    reason: str
    matched_rule: AccessRule | None


def _active_rules(event: RecognitionEvent, captured_at: datetime) -> QuerySet[AccessRule]:
    gate = event.camera.gate
    return (
        AccessRule.objects.select_related("access_list", "vehicle")
        .filter(
            is_active=True,
            vehicle__is_active=True,
            vehicle__normalized_plate=normalize_plate(event.normalized_plate),
            access_list__is_active=True,
            access_list__site=gate.site,
        )
        .filter(Q(gate__isnull=True) | Q(gate=gate))
        .filter(Q(valid_from__isnull=True) | Q(valid_from__lte=captured_at))
        .filter(Q(valid_until__isnull=True) | Q(valid_until__gte=captured_at))
    )


def _matches_schedule(rule: AccessRule, captured_at: datetime) -> bool:
    local_time = timezone.localtime(captured_at).time()
    if rule.allowed_weekdays and captured_at.weekday() not in rule.allowed_weekdays:
        return False
    if rule.allowed_from_time and local_time < rule.allowed_from_time:
        return False
    if rule.allowed_until_time and local_time > rule.allowed_until_time:
        return False
    return True


def evaluate(event: RecognitionEvent) -> DecisionResult:
    """Return a stable decision; recognition services only submit events, never decide."""
    candidates = [
        rule
        for rule in _active_rules(event, event.captured_at)
        if _matches_schedule(rule, event.captured_at)
    ]
    if not candidates:
        return DecisionResult(
            AccessDecision.Outcome.MANUAL_REVIEW, "No matching access rule.", None
        )

    decision_rank = {
        AccessDecision.Outcome.DENY: 0,
        AccessDecision.Outcome.ALLOW: 1,
        AccessDecision.Outcome.MANUAL_REVIEW: 2,
    }
    rule = min(candidates, key=lambda item: (item.priority, decision_rank[item.decision], item.pk))
    return DecisionResult(
        rule.decision,
        f"Matched {rule.access_list.kind} access rule {rule.pk}.",
        rule,
    )


@transaction.atomic
def decide(event: RecognitionEvent) -> AccessDecision:
    """Persist one decision per event, preserving the reason and rule for auditing."""
    existing = getattr(event, "decision", None)
    if existing is not None:
        return existing
    result = evaluate(event)
    return AccessDecision.objects.create(
        event=event,
        outcome=result.outcome,
        reason=result.reason,
        matched_rule=result.matched_rule,
    )
