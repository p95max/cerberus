from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

import pytest
from django.contrib.auth.models import Group
from django.test import Client, override_settings
from django.utils import timezone

from accounts.models import AuditLog, User
from accounts.roles import (
    ROLE_ADMINISTRATOR,
    ROLE_MANAGER,
    ROLE_OPERATOR,
    ROLE_READ_ONLY,
    ensure_role_groups,
)
from domain.models import (
    AccessDecision,
    BarrierCommand,
    Camera,
    Gate,
    ParkingSite,
    RecognitionEvent,
)
from domain.tasks import close_barrier_after_delay, close_due_barrier_commands, dispatch_barrier_command


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
def administrator() -> User:
    ensure_role_groups()
    user = User.objects.create_superuser(username="admin-ui", password="password")
    user.groups.add(Group.objects.get(name=ROLE_ADMINISTRATOR))
    return user


@pytest.fixture
def read_only() -> User:
    ensure_role_groups()
    user = User.objects.create_user(username="read-only-ui", password="password")
    user.groups.add(Group.objects.get(name=ROLE_READ_ONLY))
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
@pytest.mark.parametrize(
    ("account_fixture", "expected_statuses"),
    [
        pytest.param(
            "operator",
            {
                "dashboard": 200,
                "manual_review": 200,
                "barrier_control": 200,
                "configuration": 200,
                "activity_log": 403,
                "activity_export": 403,
                "django_admin": 302,
            },
            id="operator",
        ),
        pytest.param(
            "manager",
            {
                "dashboard": 200,
                "manual_review": 200,
                "barrier_control": 200,
                "configuration": 200,
                "activity_log": 200,
                "activity_export": 403,
                "django_admin": 302,
            },
            id="manager",
        ),
        pytest.param(
            "administrator",
            {
                "dashboard": 200,
                "manual_review": 200,
                "barrier_control": 200,
                "configuration": 200,
                "activity_log": 200,
                "activity_export": 200,
                "django_admin": 200,
            },
            id="administrator",
        ),
        pytest.param(
            "read_only",
            {
                "dashboard": 200,
                "manual_review": 200,
                "barrier_control": 403,
                "configuration": 200,
                "activity_log": 403,
                "activity_export": 403,
                "django_admin": 302,
            },
            id="read-only",
        ),
    ],
)
def test_console_access_matrix_by_account_type(
    request: pytest.FixtureRequest,
    account_fixture: str,
    expected_statuses: dict[str, int],
) -> None:
    client = Client()
    client.force_login(request.getfixturevalue(account_fixture))

    routes = {
        "dashboard": "/operator/",
        "manual_review": "/operator/manual-review/",
        "barrier_control": "/operator/barrier-control/",
        "configuration": "/operator/manage/sites/",
        "activity_log": "/operator/activity-log/",
        "activity_export": "/operator/activity-log/export/",
        "django_admin": "/admin/",
    }
    statuses = {name: client.get(path).status_code for name, path in routes.items()}

    assert statuses == expected_statuses
    dashboard = client.get(routes["dashboard"])
    assert (b"Activity log" in dashboard.content) is (expected_statuses["activity_log"] == 200)


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("account_fixture", "expected_status"),
    [
        pytest.param("operator", 403, id="operator"),
        pytest.param("manager", 302, id="manager"),
        pytest.param("administrator", 302, id="administrator"),
        pytest.param("read_only", 403, id="read-only"),
    ],
)
def test_configuration_write_access_matrix_by_account_type(
    request: pytest.FixtureRequest,
    account_fixture: str,
    expected_status: int,
) -> None:
    client = Client()
    client.force_login(request.getfixturevalue(account_fixture))
    external_id = f"access-matrix-{account_fixture}"

    response = client.post(
        "/operator/manage/sites/",
        {
            "external_id": external_id,
            "name": "Access matrix site",
            "address": "Test address",
            "is_active": "on",
        },
    )

    assert response.status_code == expected_status
    assert ParkingSite.objects.filter(external_id=external_id).exists() is (expected_status == 302)


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
    assert b'events awaiting manual review">1<' in response.content
    assert response.context["events_count"] == 1
    assert response.context["events"].paginator.per_page == 20
    barrier_control = client.get("/operator/barrier-control/")
    assert barrier_control.status_code == 200
    assert b"Open barrier" in barrier_control.content


@pytest.mark.django_db
def test_operator_dashboard_paginates_events(
    operator: User, manual_review_event: RecognitionEvent
) -> None:
    for index in range(20):
        event = RecognitionEvent.objects.create(
            camera=manual_review_event.camera,
            normalized_plate=f"PAGE{index:02d}",
            confidence=Decimal("0.9000"),
            captured_at=timezone.now(),
        )
        AccessDecision.objects.create(
            event=event,
            outcome=AccessDecision.Outcome.ALLOW,
            reason="Test decision.",
        )

    client = Client()
    client.force_login(operator)
    response = client.get("/operator/", {"page": 2})

    assert response.status_code == 200
    assert response.context["events_count"] == 21
    assert response.context["events"].number == 2
    assert len(response.context["events"].object_list) == 1
    assert b"21 events found" in response.content
    assert b"Page 2 of 2" in response.content


@pytest.mark.django_db
def test_event_detail_exposes_reason_audit_and_confirmed_manual_command(
    operator: User, manual_review_event: RecognitionEvent
) -> None:
    client = Client()
    client.force_login(operator)
    detail = client.get(f"/operator/events/{manual_review_event.pk}/")
    rejected = client.post(f"/operator/events/{manual_review_event.pk}/", {"action": "close"})
    accepted = client.post(
        f"/operator/events/{manual_review_event.pk}/",
        {"action": "open", "reason": "verified_visitor", "comment": "Checked at the gate."},
    )

    assert detail.status_code == 200
    assert b"No matching access rule." in detail.content
    assert b"recognition_event_received" in detail.content
    assert b"Open barrier" in detail.content
    assert rejected.status_code == 302
    assert accepted.status_code == 302
    assert manual_review_event.decision.barrier_commands.count() == 1
    command = manual_review_event.decision.barrier_commands.get()
    assert command.auto_close_at is not None
    assert command.manual_reason == "verified_visitor"
    assert command.manual_comment == "Checked at the gate."
    assert AuditLog.objects.filter(
        action="manual_barrier_command_requested",
        details__manual_reason="verified_visitor",
    ).exists()


@pytest.mark.django_db
def test_operator_can_close_manual_review_case_with_audited_actor(
    operator: User, manual_review_event: RecognitionEvent
) -> None:
    client = Client()
    client.force_login(operator)

    response = client.post(
        f"/operator/events/{manual_review_event.pk}/", {"action": "close_case"}
    )

    manual_review_event.decision.refresh_from_db()
    assert response.status_code == 302
    assert manual_review_event.decision.manual_review_closed_at is not None
    assert manual_review_event.decision.manual_review_closed_by == operator
    assert AuditLog.objects.filter(
        action="manual_review_case_closed",
        actor=operator,
        details__event_id=manual_review_event.pk,
    ).exists()

    reopen = client.post(
        f"/operator/events/{manual_review_event.pk}/", {"action": "open"}
    )
    assert reopen.status_code == 302
    assert manual_review_event.decision.barrier_commands.count() == 0

    queue = client.get("/operator/manual-review/")
    assert queue.status_code == 200
    assert b"Case" in queue.content
    assert b"Closed" in queue.content

    open_cases = client.get("/operator/manual-review/", {"case": "open"})
    closed_cases = client.get("/operator/manual-review/", {"case": "closed"})
    assert open_cases.context["events_count"] == 0
    assert closed_cases.context["events_count"] == 1


@pytest.mark.django_db
def test_operator_can_request_urgent_barrier_opening_without_an_event(
    operator: User, manual_review_event: RecognitionEvent
) -> None:
    client = Client()
    client.force_login(operator)

    response = client.post(
        "/operator/barrier-control/",
        {
            "gate": manual_review_event.camera.gate.pk,
            "request_reference": "INC-42",
            "reason": "emergency_services",
            "comment": "Ambulance arrival confirmed.",
            "duration_mode": "timed",
            "auto_close_seconds": 45,
        },
    )

    command = BarrierCommand.objects.get(request_reference="INC-42")
    assert response.status_code == 302
    assert command.decision is None
    assert command.manual_reason == "emergency_services"
    assert command.requested_by == operator
    assert command.auto_close_at is not None
    assert AuditLog.objects.filter(
        action="emergency_barrier_command_requested",
        actor=operator,
        details__command_id=command.pk,
    ).exists()


@pytest.mark.django_db
def test_activity_log_labels_independent_manual_override_commands(
    operator: User, manager: User, manual_review_event: RecognitionEvent
) -> None:
    client = Client()
    client.force_login(operator)
    client.post(
        "/operator/barrier-control/",
        {
            "gate": manual_review_event.camera.gate.pk,
            "reason": "emergency_services",
            "duration_mode": "timed",
            "auto_close_seconds": 45,
        },
    )
    command = BarrierCommand.objects.get(decision__isnull=True)

    client.force_login(manager)
    response = client.get("/operator/activity-log/")

    assert response.status_code == 200
    assert f"Barrier control #{command.pk}".encode() in response.content
    assert b"Independent manual override from Barrier control" in response.content


@pytest.mark.django_db
def test_operator_can_keep_an_urgent_barrier_command_open_until_manual_close(
    operator: User, manual_review_event: RecognitionEvent
) -> None:
    client = Client()
    client.force_login(operator)
    client.post(
        "/operator/barrier-control/",
        {
            "gate": manual_review_event.camera.gate.pk,
            "request_reference": "INC-OPEN",
            "reason": "fire_evacuation",
            "duration_mode": "indefinite",
        },
    )
    command = BarrierCommand.objects.get(request_reference="INC-OPEN")

    assert command.auto_close_at is None
    page = client.get("/operator/barrier-control/")
    assert b"Open until closed manually" in page.content
    assert b"Barrier open without a timer" in page.content

    close_response = client.post(
        "/operator/barrier-control/", {"action": "close", "command_id": command.pk}
    )
    command.refresh_from_db()
    assert close_response.status_code == 302
    assert command.status == BarrierCommand.Status.CLOSED
    assert AuditLog.objects.filter(
        action="barrier_closed_manually", details__command_id=command.pk
    ).exists()


@pytest.mark.django_db
def test_automatic_barrier_close_is_recorded(
    operator: User, manual_review_event: RecognitionEvent
) -> None:
    command = manual_review_event.decision.barrier_commands.create(
        gate=manual_review_event.camera.gate,
        requested_by=operator,
        auto_close_at=timezone.now(),
        status=BarrierCommand.Status.ACKNOWLEDGED,
    )

    result = close_barrier_after_delay.run(command.pk)

    command.refresh_from_db()
    assert result["status"] == "closed"
    assert command.status == "closed"
    assert command.closed_at is not None
    assert AuditLog.objects.filter(
        action="barrier_closed_automatically",
        details__command_id=command.pk,
    ).exists()


@pytest.mark.django_db
def test_due_barrier_command_is_reconciled_after_a_missed_eta_task(
    operator: User, manual_review_event: RecognitionEvent
) -> None:
    command = BarrierCommand.objects.create(
        gate=manual_review_event.camera.gate,
        requested_by=operator,
        auto_close_at=timezone.now() - timedelta(seconds=1),
        status=BarrierCommand.Status.ACKNOWLEDGED,
    )

    result = close_due_barrier_commands.run()

    command.refresh_from_db()
    assert result["scheduled"] == 1
    assert command.status == BarrierCommand.Status.CLOSED


@pytest.mark.django_db
@override_settings(MOCK_BARRIER_AVAILABLE=False, BARRIER_COMMAND_MAX_RETRIES=1)
def test_unavailable_barrier_controller_marks_command_failed(
    operator: User, manual_review_event: RecognitionEvent
) -> None:
    command = manual_review_event.decision.barrier_commands.create(
        gate=manual_review_event.camera.gate,
        requested_by=operator,
        auto_close_at=timezone.now(),
    )

    result = dispatch_barrier_command.run(command.pk)

    command.refresh_from_db()
    assert result["status"] == "failed"
    assert command.last_error == "Mock barrier controller is unavailable."
    assert AuditLog.objects.filter(action="barrier_command_failed").exists()


@pytest.mark.django_db
@override_settings(
    MOCK_BARRIER_DELAY_SECONDS=4,
    BARRIER_CONTROLLER_TIMEOUT_SECONDS=3,
    BARRIER_COMMAND_MAX_RETRIES=1,
)
def test_slow_barrier_controller_times_out(
    operator: User, manual_review_event: RecognitionEvent
) -> None:
    command = manual_review_event.decision.barrier_commands.create(
        gate=manual_review_event.camera.gate,
        requested_by=operator,
        auto_close_at=timezone.now(),
    )

    dispatch_barrier_command.run(command.pk)

    command.refresh_from_db()
    assert command.status == "failed"
    assert command.last_error == "Mock barrier controller timed out."


@pytest.mark.django_db
def test_operator_can_view_configuration_but_only_manager_can_change_it(
    operator: User, manager: User, manual_review_event: RecognitionEvent
) -> None:
    client = Client()
    client.force_login(operator)
    response = client.get("/operator/manage/vehicles/")
    assert response.status_code == 200
    assert b"Configuration (read-only)" in response.content
    assert b"Add Vehicle" not in response.content
    assert b">Edit<" not in response.content
    assert client.post("/operator/manage/vehicles/", {}).status_code == 403
    gate_response = client.get(f"/operator/manage/gates/{manual_review_event.camera.gate.pk}/")
    assert gate_response.status_code == 200
    assert b"(read-only)" in gate_response.content
    assert client.post(f"/operator/manage/gates/{manual_review_event.camera.gate.pk}/", {}).status_code == 403

    client.force_login(manager)
    response = client.get("/operator/manage/vehicles/")
    assert response.status_code == 200
    assert b"Vehicles" in response.content


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("resource", "description"),
    (
        ("sites", b"Parking locations and objects"),
        ("gates", b"Entry and exit points"),
        ("cameras", b"Recognition cameras"),
        ("vehicles", b"Known vehicle records"),
        ("access-lists", b"Allow and deny lists"),
        ("access-rules", b"Defines whether a specific vehicle is allowed or denied"),
        ("retention", b"How long recognition data"),
        ("barrier", b"Default automatic-close delay"),
    ),
)
def test_every_configuration_tab_explains_its_purpose(
    manager: User, resource: str, description: bytes
) -> None:
    client = Client()
    client.force_login(manager)

    response = client.get(f"/operator/manage/{resource}/")

    assert response.status_code == 200
    assert description in response.content


@pytest.mark.django_db
def test_activity_log_is_filterable_and_sortable_for_managers(
    operator: User, manager: User
) -> None:
    AuditLog.objects.create(action="manual_review_case_closed", actor=manager)
    AuditLog.objects.create(action="login_failed")
    client = Client()

    client.force_login(operator)
    assert client.get("/operator/activity-log/").status_code == 403

    client.force_login(manager)
    response = client.get(
        "/operator/activity-log/",
        {"action": "manual_review_case_closed", "actor": manager.pk, "sort": "oldest"},
    )
    assert response.status_code == 200
    assert b"Activity log" in response.content
    assert b"Manual-review case closed" in response.content
    assert b"Sign-in failed" not in response.content
    assert response.context["entries_count"] == 1


@pytest.mark.django_db
@pytest.mark.parametrize(
    "sort",
    ("time", "action", "user", "event", "command", "ip_address", "details"),
)
def test_activity_log_supports_sorting_by_every_visible_column(manager: User, sort: str) -> None:
    AuditLog.objects.create(
        action="manual_review_case_closed",
        actor=manager,
        ip_address="192.0.2.10",
        details={"event_id": 20, "command_id": 4, "manual_comment": "Second"},
    )
    AuditLog.objects.create(
        action="login_succeeded",
        ip_address="192.0.2.2",
        details={"event_id": 2, "command_id": 11, "manual_comment": "First"},
    )
    client = Client()
    client.force_login(manager)

    response = client.get("/operator/activity-log/", {"sort": sort, "direction": "asc"})

    assert response.status_code == 200
    assert response.context["sort"] == sort
    assert response.context["sort_direction"] == "asc"
    assert f"sort={sort}&amp;direction=desc".encode() in response.content


@pytest.mark.django_db
def test_manager_configuration_changes_are_audited_and_have_a_dedicated_log_tab(
    manager: User,
) -> None:
    client = Client()
    client.force_login(manager)
    create = client.post(
        "/operator/manage/sites/",
        {
            "external_id": "audit-site",
            "name": "Audit Site",
            "address": "Initial address",
            "is_active": "on",
        },
    )
    site = ParkingSite.objects.get(external_id="audit-site")
    update = client.post(
        f"/operator/manage/sites/{site.pk}/",
        {
            "external_id": "audit-site",
            "name": "Updated Audit Site",
            "address": "Updated address",
            "is_active": "on",
        },
    )

    assert create.status_code == 302
    assert update.status_code == 302
    created_audit = AuditLog.objects.get(action="configuration_created", actor=manager)
    updated_audit = AuditLog.objects.get(action="configuration_updated", actor=manager)
    assert created_audit.details["resource"] == "sites"
    assert "name: Audit Site → Updated Audit Site" in updated_audit.details["change_summary"]

    response = client.get("/operator/activity-log/", {"view": "configuration"})

    assert response.status_code == 200
    assert response.context["log_view"] == "configuration"
    assert b"Configuration changes" in response.content
    assert b"Configuration record created" in response.content
    assert b"Configuration record updated" in response.content


@pytest.mark.django_db
def test_only_administrator_can_download_activity_log_json(
    manager: User, administrator: User
) -> None:
    AuditLog.objects.create(action="login_succeeded", actor=administrator)
    client = Client()

    client.force_login(manager)
    assert client.get("/operator/activity-log/export/").status_code == 403

    client.force_login(administrator)
    page = client.get("/operator/activity-log/")
    export = client.get("/operator/activity-log/export/", {"action": "login_succeeded"})
    assert b"Download JSON" in page.content
    assert export.status_code == 200
    assert export["Content-Type"].startswith("application/json")
    assert export.json()[0]["action"] == "login_succeeded"


@pytest.mark.django_db
def test_retention_settings_are_editable_for_manager_and_read_only_for_operator(
    operator: User, manager: User
) -> None:
    client = Client()
    client.force_login(operator)
    response = client.get("/operator/manage/retention/")

    assert response.status_code == 200
    assert b"Data retention (read-only)" in response.content
    assert b"Retention levels" in response.content
    assert b"Save" not in response.content

    client.force_login(manager)
    response = client.get("/operator/manage/retention/")

    assert response.status_code == 200
    assert b"Clear image metadata" in response.content
    assert b"Save" in response.content


@pytest.mark.django_db
def test_barrier_settings_are_editable_for_manager_and_read_only_for_operator(
    operator: User, manager: User
) -> None:
    client = Client()
    client.force_login(operator)
    response = client.get("/operator/manage/barrier/")

    assert response.status_code == 200
    assert b"Barrier control (read-only)" in response.content
    assert b"10 seconds" in response.content

    client.force_login(manager)
    response = client.get("/operator/manage/barrier/")

    assert response.status_code == 200
    assert b"Automatic close delay (seconds)" in response.content
    assert b"Save" in response.content
