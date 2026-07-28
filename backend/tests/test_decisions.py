from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from django.db import IntegrityError, transaction
from django.utils import timezone

from domain.models import (
    AccessDecision,
    AccessList,
    AccessRule,
    Camera,
    Gate,
    ParkingSite,
    RecognitionEvent,
    Vehicle,
)
from domain.services.decisions import decide, evaluate, normalize_plate


@pytest.fixture
def parking_setup() -> dict[str, object]:
    site = ParkingSite.objects.create(external_id="site-1", name="Main site")
    gate = Gate.objects.create(
        site=site,
        external_id="gate-1",
        name="North gate",
        direction=Gate.Direction.ENTRY,
    )
    camera = Camera.objects.create(gate=gate, external_id="camera-1", name="North camera")
    vehicle = Vehicle.objects.create(normalized_plate="A123BC77", display_plate="A 123 BC 77")
    return {"site": site, "gate": gate, "camera": camera, "vehicle": vehicle}


def event_for(parking_setup: dict[str, object], plate: str = "a-123 bc 77") -> RecognitionEvent:
    return RecognitionEvent.objects.create(
        camera=parking_setup["camera"],  # type: ignore[arg-type]
        normalized_plate=plate,
        confidence=Decimal("0.9900"),
        captured_at=timezone.now(),
    )


def rule_for(
    parking_setup: dict[str, object],
    *,
    kind: str,
    decision: str,
    priority: int = 100,
    **kwargs: object,
) -> AccessRule:
    access_list = AccessList.objects.create(
        site=parking_setup["site"],  # type: ignore[arg-type]
        name=f"{kind}-{decision}-{priority}-{AccessList.objects.count()}",
        kind=kind,
    )
    return AccessRule.objects.create(
        access_list=access_list,
        vehicle=parking_setup["vehicle"],  # type: ignore[arg-type]
        decision=decision,
        priority=priority,
        **kwargs,
    )


@pytest.mark.django_db
def test_plate_normalization_and_whitelist_allow(parking_setup: dict[str, object]) -> None:
    rule = rule_for(
        parking_setup,
        kind=AccessList.Kind.WHITELIST,
        decision=AccessRule.Decision.ALLOW,
    )

    result = evaluate(event_for(parking_setup))

    assert normalize_plate("a-123 bc 77") == "A123BC77"
    assert result.outcome == AccessDecision.Outcome.ALLOW
    assert result.matched_rule == rule
    assert "whitelist" in result.reason


@pytest.mark.django_db
def test_blacklist_deny_wins_equal_priority(parking_setup: dict[str, object]) -> None:
    rule_for(
        parking_setup,
        kind=AccessList.Kind.WHITELIST,
        decision=AccessRule.Decision.ALLOW,
        priority=10,
    )
    deny_rule = rule_for(
        parking_setup,
        kind=AccessList.Kind.BLACKLIST,
        decision=AccessRule.Decision.DENY,
        priority=10,
    )

    result = evaluate(event_for(parking_setup))

    assert result.outcome == AccessDecision.Outcome.DENY
    assert result.matched_rule == deny_rule


@pytest.mark.django_db
def test_no_applicable_rule_requires_manual_review(parking_setup: dict[str, object]) -> None:
    result = evaluate(event_for(parking_setup, "X000XX77"))

    assert result.outcome == AccessDecision.Outcome.MANUAL_REVIEW
    assert result.matched_rule is None


@pytest.mark.django_db
def test_gate_and_temporary_schedule_restrictions(parking_setup: dict[str, object]) -> None:
    captured_at = timezone.now()
    applicable = rule_for(
        parking_setup,
        kind=AccessList.Kind.WHITELIST,
        decision=AccessRule.Decision.ALLOW,
        gate=parking_setup["gate"],
        allowed_weekdays=[captured_at.weekday()],
        valid_from=captured_at - timedelta(minutes=1),
        valid_until=captured_at + timedelta(minutes=1),
    )
    rule_for(
        parking_setup,
        kind=AccessList.Kind.BLACKLIST,
        decision=AccessRule.Decision.DENY,
        priority=1,
        valid_until=captured_at - timedelta(seconds=1),
    )
    event = event_for(parking_setup)
    event.captured_at = captured_at
    event.save(update_fields=("captured_at",))

    result = evaluate(event)

    assert result.outcome == AccessDecision.Outcome.ALLOW
    assert result.matched_rule == applicable


@pytest.mark.django_db
def test_decision_is_idempotent_and_stores_reason_and_rule(
    parking_setup: dict[str, object],
) -> None:
    rule = rule_for(
        parking_setup,
        kind=AccessList.Kind.WHITELIST,
        decision=AccessRule.Decision.ALLOW,
    )
    event = event_for(parking_setup)

    first = decide(event)
    second = decide(event)

    assert first == second
    assert first.matched_rule == rule
    assert first.reason == f"Matched whitelist access rule {rule.pk}."


@pytest.mark.django_db(transaction=True)
def test_recognition_request_id_is_unique(parking_setup: dict[str, object]) -> None:
    request_id = uuid4()
    RecognitionEvent.objects.create(
        camera=parking_setup["camera"],  # type: ignore[arg-type]
        normalized_plate="A123BC77",
        confidence=Decimal("0.9900"),
        captured_at=timezone.now(),
        recognition_request_id=request_id,
    )

    with transaction.atomic():
        with pytest.raises(IntegrityError):
            RecognitionEvent.objects.create(
                camera=parking_setup["camera"],  # type: ignore[arg-type]
                normalized_plate="A123BC77",
                confidence=Decimal("0.9900"),
                captured_at=timezone.now(),
                recognition_request_id=request_id,
            )
