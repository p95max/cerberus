from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, ClassVar
from uuid import uuid4

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.auth.views import LoginView, LogoutView
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import IntegerField, QuerySet, TextField
from django.db.models.fields.json import KeyTextTransform
from django.db.models.functions import Cast
from django.http import HttpRequest, HttpResponse, HttpResponseForbidden, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views import View
from django.views.generic import DetailView

from accounts.audit import record_audit
from accounts.models import AuditLog, User
from accounts.roles import ROLE_ADMINISTRATOR, ROLE_MANAGER, ROLE_OPERATOR, ROLE_READ_ONLY, has_role
from domain.forms import (
    AccessListForm,
    AccessRuleForm,
    BarrierControlSettingsForm,
    CameraForm,
    DemoRecognitionSubmissionForm,
    EmergencyBarrierOpenForm,
    GateForm,
    ManualBarrierOpenForm,
    ParkingSiteForm,
    RecognitionRetentionPolicyForm,
    VehicleForm,
)
from domain.models import (
    AccessDecision,
    AccessList,
    AccessRule,
    BarrierCommand,
    BarrierControlSettings,
    Camera,
    Gate,
    ParkingSite,
    RecognitionEvent,
    RecognitionRetentionPolicy,
    Vehicle,
)
from domain.services.barrier import barrier_auto_close_seconds, barrier_control_defaults
from domain.services.retention import retention_policy_defaults
from domain.services.recognition import submit_recognition_event
from domain.tasks import dispatch_barrier_command


class OperatorLoginView(LoginView):
    template_name = "domain/operator/login.html"
    redirect_authenticated_user = True


class OperatorLogoutView(LogoutView):
    next_page = "operator-login"


class OperatorAccessMixin(LoginRequiredMixin):
    allowed_roles: ClassVar[tuple[str, ...]] = (
        ROLE_ADMINISTRATOR,
        ROLE_MANAGER,
        ROLE_OPERATOR,
        ROLE_READ_ONLY,
    )

    def dispatch(self, request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponse:
        if not has_role(request.user, self.allowed_roles):
            return HttpResponseForbidden("Operator role is required.")
        return super().dispatch(request, *args, **kwargs)


def filtered_events(request: HttpRequest) -> QuerySet[RecognitionEvent]:
    events = RecognitionEvent.objects.select_related("camera__gate__site", "decision").order_by(
        "-captured_at"
    )
    if site := request.GET.get("site"):
        events = events.filter(camera__gate__site_id=site)
    if gate := request.GET.get("gate"):
        events = events.filter(camera__gate_id=gate)
    if plate := request.GET.get("plate"):
        normalized = "".join(char for char in plate.upper() if char.isalnum())
        events = events.filter(normalized_plate__icontains=normalized)
    if decision := request.GET.get("decision"):
        events = events.filter(decision__outcome=decision)
    if case_status := request.GET.get("case"):
        if case_status == "open":
            events = events.filter(
                decision__outcome=AccessDecision.Outcome.MANUAL_REVIEW,
                decision__manual_review_closed_at__isnull=True,
            )
        elif case_status == "closed":
            events = events.filter(
                decision__outcome=AccessDecision.Outcome.MANUAL_REVIEW,
                decision__manual_review_closed_at__isnull=False,
            )
    for parameter, lookup in (("from", "captured_at__gte"), ("to", "captured_at__lte")):
        if value := request.GET.get(parameter):
            try:
                parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
                events = events.filter(
                    **{lookup: timezone.make_aware(parsed) if timezone.is_naive(parsed) else parsed}
                )
            except ValueError:
                continue
    return events


class OperatorDashboardView(OperatorAccessMixin, View):
    template_name = "domain/operator/dashboard.html"

    def get(self, request: HttpRequest) -> HttpResponse:
        return self.render_events(
            request, filtered_events(request), "Recent recognition events", "📋"
        )

    def render_events(
        self,
        request: HttpRequest,
        events: QuerySet[RecognitionEvent],
        title: str,
        heading_icon: str,
    ) -> HttpResponse:
        paginator = Paginator(events, 20)
        page_obj = paginator.get_page(request.GET.get("page"))
        query_params = request.GET.copy()
        query_params.pop("page", None)
        return render(
            request,
            self.template_name,
            {
                "events": page_obj,
                "events_count": paginator.count,
                "query_string": query_params.urlencode(),
                "title": title,
                "heading_icon": heading_icon,
                "sites": ParkingSite.objects.filter(is_active=True),
                "gates": Gate.objects.filter(is_active=True).select_related("site"),
                "outcomes": AccessDecision.Outcome.choices,
                "show_case_status": title == "Manual review queue",
            },
        )


class ManualReviewQueueView(OperatorDashboardView):
    def get(self, request: HttpRequest) -> HttpResponse:
        events = filtered_events(request).filter(
            decision__outcome=AccessDecision.Outcome.MANUAL_REVIEW
        )
        return self.render_events(request, events, "Manual review queue", "🔎")


class BarrierControlQueueView(OperatorAccessMixin, View):
    template_name = "domain/operator/barrier_control.html"
    allowed_roles = (ROLE_ADMINISTRATOR, ROLE_MANAGER, ROLE_OPERATOR)

    @staticmethod
    def emergency_form(data: Any | None = None) -> EmergencyBarrierOpenForm:
        return EmergencyBarrierOpenForm(
            data,
            initial={"auto_close_seconds": barrier_auto_close_seconds()},
        )

    def render_page(
        self, request: HttpRequest, emergency_form: EmergencyBarrierOpenForm, status: int = 200
    ) -> HttpResponse:
        active_commands = BarrierCommand.objects.select_related("gate__site", "requested_by").filter(
            decision__isnull=True,
            status__in=(
                BarrierCommand.Status.PENDING,
                BarrierCommand.Status.SENT,
                BarrierCommand.Status.ACKNOWLEDGED,
            )
        ).order_by("-created_at")
        return render(
            request,
            self.template_name,
            {"emergency_form": emergency_form, "active_commands": active_commands},
            status=status,
        )

    def get(self, request: HttpRequest) -> HttpResponse:
        return self.render_page(request, self.emergency_form())

    def post(self, request: HttpRequest) -> HttpResponse:
        if request.POST.get("action") == "close":
            command = get_object_or_404(
                BarrierCommand,
                pk=request.POST.get("command_id"),
                decision__isnull=True,
                status__in=(
                    BarrierCommand.Status.PENDING,
                    BarrierCommand.Status.SENT,
                    BarrierCommand.Status.ACKNOWLEDGED,
                ),
            )
            command.status = BarrierCommand.Status.CLOSED
            command.closed_at = timezone.now()
            command.save(update_fields=("status", "closed_at", "updated_at"))
            record_audit(
                "barrier_closed_manually",
                request=request,
                actor=request.user,
                details={
                    "command_id": command.pk,
                    "gate_id": command.gate_id,
                    "gate_name": str(command.gate),
                    "request_reference": command.request_reference,
                    "opening_mode": "indefinite" if command.auto_close_at is None else "timed",
                },
            )
            messages.success(request, f"Barrier command #{command.pk} closed.")
            return redirect("operator-barrier-control")

        form = self.emergency_form(request.POST)
        if not form.is_valid():
            return self.render_page(request, form, status=400)

        gate = form.cleaned_data["gate"]
        active_command = BarrierCommand.objects.filter(
            gate=gate,
            status__in=(
                BarrierCommand.Status.PENDING,
                BarrierCommand.Status.SENT,
                BarrierCommand.Status.ACKNOWLEDGED,
            ),
        ).exists()
        if active_command:
            form.add_error(None, "A barrier command is already active for this gate.")
            return self.render_page(request, form, status=400)

        auto_close_seconds = (
            form.cleaned_data["auto_close_seconds"]
            if form.cleaned_data["duration_mode"] == "timed"
            else None
        )
        auto_close_at = (
            timezone.now() + timedelta(seconds=auto_close_seconds)
            if auto_close_seconds is not None
            else None
        )
        reason = form.cleaned_data["reason"]
        command = BarrierCommand.objects.create(
            gate=gate,
            requested_by=request.user,
            auto_close_at=auto_close_at,
            manual_reason=reason,
            manual_comment=form.cleaned_data["comment"],
            request_reference=form.cleaned_data["request_reference"],
        )
        record_audit(
            "emergency_barrier_command_requested",
            request=request,
            actor=request.user,
            details={
                "command_id": command.pk,
                "gate_id": gate.pk,
                "gate_name": str(gate),
                "request_reference": command.request_reference,
                "manual_reason": reason,
                "manual_reason_label": dict(ManualBarrierOpenForm.REASON_CHOICES)[reason],
                "manual_comment": command.manual_comment,
                "opening_mode": form.cleaned_data["duration_mode"],
                "auto_close_seconds": auto_close_seconds,
                "auto_close_at": auto_close_at.isoformat() if auto_close_at else None,
            },
        )
        transaction.on_commit(lambda: dispatch_barrier_command.delay(command.pk))
        messages.success(
            request,
            (
                f"Urgent barrier command #{command.pk} queued; closing in {auto_close_seconds} seconds."
                if auto_close_seconds is not None
                else f"Urgent barrier command #{command.pk} queued; it remains open until closed manually."
            ),
        )
        return redirect("operator-barrier-control")


class DemoRecognitionSubmissionView(OperatorAccessMixin, View):
    template_name = "domain/operator/demo_submit.html"
    allowed_roles = (ROLE_ADMINISTRATOR, ROLE_MANAGER)

    def get(self, request: HttpRequest) -> HttpResponse:
        if not settings.DEMO_EVENT_SUBMISSION_ENABLED:
            return HttpResponseForbidden("Demo event submission is disabled.")
        return render(request, self.template_name, {"form": DemoRecognitionSubmissionForm()})

    def post(self, request: HttpRequest) -> HttpResponse:
        if not settings.DEMO_EVENT_SUBMISSION_ENABLED:
            return HttpResponseForbidden("Demo event submission is disabled.")
        form = DemoRecognitionSubmissionForm(request.POST)
        if not form.is_valid():
            return render(request, self.template_name, {"form": form}, status=400)
        camera = form.cleaned_data["camera"]
        submission = submit_recognition_event(
            recognition_request_id=uuid4(),
            plate_number=form.cleaned_data["plate_number"],
            confidence=form.cleaned_data["confidence"],
            camera_external_id=camera.external_id,
            direction=camera.gate.direction,
            captured_at=timezone.now(),
            image_metadata={"source": "operator-demo-submit"},
            submitted_by=request.user,
        )
        record_audit(
            "recognition_event_received",
            request=request,
            actor=request.user,
            details={
                "event_id": submission.event.pk,
                "decision": submission.decision.outcome,
                "source": "operator_demo_submit",
            },
        )
        messages.success(
            request,
            f"Demo event #{submission.event.pk} created: {submission.decision.outcome}.",
        )
        return redirect("operator-event-detail", pk=submission.event.pk)

class EventDetailView(OperatorAccessMixin, DetailView):
    model = RecognitionEvent
    template_name = "domain/operator/event_detail.html"
    context_object_name = "event"

    def get_queryset(self) -> QuerySet[RecognitionEvent]:
        return RecognitionEvent.objects.select_related(
            "camera__gate__site", "decision__matched_rule", "decision__manual_review_closed_by"
        )

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        context = super().get_context_data(**kwargs)
        context.setdefault("manual_open_form", ManualBarrierOpenForm())
        context["audit_history"] = AuditLog.objects.filter(details__event_id=self.object.pk)
        latest_barrier_command = self.object.decision.barrier_commands.order_by("-created_at").first()
        context["active_barrier_command"] = (
            self.object.decision.barrier_commands.filter(
                status__in=(
                    BarrierCommand.Status.PENDING,
                    BarrierCommand.Status.SENT,
                    BarrierCommand.Status.ACKNOWLEDGED,
                ),
                auto_close_at__isnull=False,
            )
            .order_by("-created_at")
            .first()
        )
        barrier_status, barrier_status_label = "closed", "Closed"
        if latest_barrier_command is not None:
            if latest_barrier_command.status == BarrierCommand.Status.ACKNOWLEDGED:
                barrier_status, barrier_status_label = "open", "Open"
            elif latest_barrier_command.status in {
                BarrierCommand.Status.PENDING,
                BarrierCommand.Status.SENT,
            }:
                barrier_status, barrier_status_label = "transition", "Opening"
            elif latest_barrier_command.status == BarrierCommand.Status.FAILED:
                barrier_status, barrier_status_label = "failed", "Controller error"
        context["barrier_status"] = barrier_status
        context["barrier_status_label"] = barrier_status_label
        return context

    def post(self, request: HttpRequest, pk: int) -> HttpResponse:
        event = get_object_or_404(self.get_queryset(), pk=pk)
        if not has_role(request.user, (ROLE_ADMINISTRATOR, ROLE_MANAGER, ROLE_OPERATOR)):
            return HttpResponseForbidden("Operator role is required for a manual barrier command.")
        if event.decision.outcome != AccessDecision.Outcome.MANUAL_REVIEW:
            messages.error(
                request, "Manual barrier commands are available only for manual-review events."
            )
            return redirect("operator-event-detail", pk=event.pk)
        action = request.POST.get("action")
        if action == "close_case":
            if event.decision.manual_review_closed_at is not None:
                messages.error(request, "This manual-review case is already closed.")
            else:
                event.decision.manual_review_closed_at = timezone.now()
                event.decision.manual_review_closed_by = request.user
                event.decision.save(
                    update_fields=("manual_review_closed_at", "manual_review_closed_by", "updated_at")
                )
                record_audit(
                    "manual_review_case_closed",
                    request=request,
                    actor=request.user,
                    details={"event_id": event.pk},
                )
                messages.success(request, "Manual-review case closed.")
            return redirect("operator-event-detail", pk=event.pk)
        if event.decision.manual_review_closed_at is not None:
            messages.error(request, "A closed manual-review case cannot open the barrier.")
            return redirect("operator-event-detail", pk=event.pk)
        if action != "open":
            messages.error(request, "Choose Open to queue a manual barrier command.")
            return redirect("operator-event-detail", pk=event.pk)
        manual_open_form = ManualBarrierOpenForm(request.POST)
        if not manual_open_form.is_valid():
            self.object = event
            return self.render_to_response(
                self.get_context_data(manual_open_form=manual_open_form), status=400
            )
        active_command = event.decision.barrier_commands.filter(
            status__in=(
                BarrierCommand.Status.PENDING,
                BarrierCommand.Status.SENT,
                BarrierCommand.Status.ACKNOWLEDGED,
            )
        ).order_by("-created_at").first()
        if active_command is not None:
            messages.error(
                request,
                (
                    "Automatic gate-close timer is already active."
                    if active_command.auto_close_at
                    else "A barrier command is already active for this event."
                ),
            )
            return redirect("operator-event-detail", pk=event.pk)
        auto_close_at = timezone.now() + timedelta(seconds=barrier_auto_close_seconds())
        manual_reason = manual_open_form.cleaned_data["reason"]
        manual_comment = manual_open_form.cleaned_data["comment"]
        command = BarrierCommand.objects.create(
            decision=event.decision,
            gate=event.camera.gate,
            requested_by=request.user,
            auto_close_at=auto_close_at,
            manual_reason=manual_reason,
            manual_comment=manual_comment,
        )
        record_audit(
            "manual_barrier_command_requested",
            request=request,
            actor=request.user,
            details={
                "event_id": event.pk,
                "command_id": command.pk,
                "gate_name": str(event.camera.gate),
                "auto_close_at": auto_close_at.isoformat(),
                "manual_reason": manual_reason,
                "manual_reason_label": dict(ManualBarrierOpenForm.REASON_CHOICES)[manual_reason],
                "manual_comment": manual_comment,
            },
        )
        transaction.on_commit(lambda: dispatch_barrier_command.delay(command.pk))
        messages.success(
            request,
            "Barrier opened in the mock controller; automatic close is scheduled.",
        )
        return redirect("operator-event-detail", pk=event.pk)


RESOURCE_CONFIG: dict[str, tuple[type[Any], type[Any], str, str]] = {
    "sites": (ParkingSite, ParkingSiteForm, "Parking sites/Objects", "parking site/object"),
    "gates": (Gate, GateForm, "Gates", "gate"),
    "cameras": (Camera, CameraForm, "Cameras", "camera"),
    "vehicles": (Vehicle, VehicleForm, "Vehicles", "vehicle"),
    "access-lists": (AccessList, AccessListForm, "Access lists", "access list"),
    "access-rules": (AccessRule, AccessRuleForm, "Access rules", "access rule"),
    "retention": (
        RecognitionRetentionPolicy,
        RecognitionRetentionPolicyForm,
        "Data retention",
        "retention policy",
    ),
    "barrier": (
        BarrierControlSettings,
        BarrierControlSettingsForm,
        "Barrier control",
        "barrier control settings",
    ),
}

RESOURCE_DESCRIPTIONS = {
    "sites": "Parking locations and objects that group the gates used by the access system.",
    "gates": "Entry and exit points where access decisions are applied.",
    "cameras": "Recognition cameras connected to a specific gate.",
    "vehicles": "Known vehicle records used by access lists and rules.",
    "access-lists": "Allow and deny lists that group vehicle access policies.",
    "access-rules": (
        "Defines whether a specific vehicle is allowed or denied at a selected gate; "
        "priority resolves conflicting rules."
    ),
    "retention": "How long recognition data and aggregate cleanup records are retained.",
    "barrier": "Default automatic-close delay for the mock barrier controller.",
}

SINGLETON_RESOURCE_DEFAULTS = {
    "retention": retention_policy_defaults,
    "barrier": barrier_control_defaults,
}


def audit_value(value: Any) -> str:
    if value is None:
        return "—"
    if isinstance(value, bool):
        return "Enabled" if value else "Disabled"
    if hasattr(value, "pk"):
        return str(value)
    if isinstance(value, (list, tuple)):
        return ", ".join(audit_value(item) for item in value)
    return str(value)


def record_configuration_change(
    *,
    request: HttpRequest,
    form: Any,
    resource: str,
    title: str,
    item: Any,
    created: bool,
) -> None:
    changes = {
        field: {
            "from": audit_value(form.initial.get(field)),
            "to": audit_value(form.cleaned_data.get(field)),
        }
        for field in form.changed_data
    }
    record_audit(
        "configuration_created" if created else "configuration_updated",
        request=request,
        actor=request.user,
        details={
            "resource": resource,
            "resource_label": title,
            "object_id": item.pk,
            "object_label": str(item),
            "changes": changes,
            "change_summary": "; ".join(
                f"{field}: {values['from']} → {values['to']}" for field, values in changes.items()
            ),
        },
    )


class ManagerAccessMixin(OperatorAccessMixin):
    allowed_roles = (ROLE_ADMINISTRATOR, ROLE_MANAGER)


class ActivityLogView(ManagerAccessMixin, View):
    template_name = "domain/operator/activity_log.html"
    action_labels = {
        "barrier_closed_automatically": "Barrier closed automatically",
        "barrier_command_acknowledged": "Barrier command acknowledged",
        "barrier_command_failed": "Barrier command failed",
        "barrier_command_retry_scheduled": "Barrier command retry scheduled",
        "barrier_closed_manually": "Barrier closed manually",
        "configuration_created": "Configuration record created",
        "configuration_updated": "Configuration record updated",
        "emergency_barrier_command_requested": "Urgent barrier opening requested",
        "login_failed": "Sign-in failed",
        "login_locked": "Sign-in locked",
        "login_succeeded": "Signed in",
        "logout": "Signed out",
        "manual_barrier_command_requested": "Manual barrier opening requested",
        "manual_review_case_closed": "Manual-review case closed",
        "permission_denied": "Permission denied",
        "recognition_event_metadata_purged": "Recognition image metadata cleared",
        "recognition_event_received": "Recognition event received",
        "recognition_events_purged": "Recognition events purged",
    }
    sort_fields = {
        "time": "created_at",
        "action": "action",
        "user": "actor__username",
        "event": "event_sort_id",
        "command": "command_sort_id",
        "ip_address": "ip_address",
        "details": "details_sort_text",
    }

    def filtered_entries(self, request: HttpRequest) -> tuple[QuerySet[AuditLog], str, str, str]:
        entries = AuditLog.objects.select_related("actor").annotate(
            event_sort_id=Cast(KeyTextTransform("event_id", "details"), IntegerField()),
            command_sort_id=Cast(KeyTextTransform("command_id", "details"), IntegerField()),
            details_sort_text=Cast("details", TextField()),
        )
        log_view = request.GET.get("view", "all")
        if log_view not in {"all", "configuration"}:
            log_view = "all"
        if log_view == "configuration":
            entries = entries.filter(action__in=("configuration_created", "configuration_updated"))
        if action := request.GET.get("action"):
            entries = entries.filter(action=action)
        if actor_id := request.GET.get("actor"):
            if actor_id.isdigit():
                entries = entries.filter(actor_id=int(actor_id))

        sort = request.GET.get("sort", "time")
        direction = request.GET.get("direction")
        legacy_sorts = {
            "newest": ("time", "desc"),
            "oldest": ("time", "asc"),
            "actor": ("user", "asc"),
        }
        if sort in legacy_sorts and direction is None:
            sort, direction = legacy_sorts[sort]
        if sort not in self.sort_fields:
            sort = "time"
        if direction not in {"asc", "desc"}:
            direction = "desc" if sort == "time" else "asc"
        prefix = "-" if direction == "desc" else ""
        entries = entries.order_by(f"{prefix}{self.sort_fields[sort]}", f"{prefix}pk")
        return entries, sort, direction, log_view

    def get(self, request: HttpRequest) -> HttpResponse:
        entries, sort, direction, log_view = self.filtered_entries(request)
        paginator = Paginator(entries, 20)
        page_obj = paginator.get_page(request.GET.get("page"))
        command_ids = [
            entry.details.get("command_id")
            for entry in page_obj
            if entry.details and entry.details.get("command_id")
        ]
        commands = BarrierCommand.objects.in_bulk(command_ids)
        for entry in page_obj:
            self.decorate_entry(entry, commands.get((entry.details or {}).get("command_id")))
        query_params = request.GET.copy()
        query_params.pop("page", None)
        sort_query_params = query_params.copy()
        sort_query_params.pop("sort", None)
        sort_query_params.pop("direction", None)
        sort_links = {}
        for key in self.sort_fields:
            params = sort_query_params.copy()
            params["sort"] = key
            params["direction"] = "desc" if key == sort and direction == "asc" else "asc"
            sort_links[key] = params.urlencode()
        return render(
            request,
            self.template_name,
            {
                "entries": page_obj,
                "entries_count": paginator.count,
                "actions": [
                    (action, self.action_labels.get(action, action.replace("_", " ").capitalize()))
                    for action in AuditLog.objects.order_by("action")
                    .values_list("action", flat=True)
                    .distinct()
                ],
                "actors": User.objects.filter(audit_events__isnull=False).order_by("username").distinct(),
                "sort": sort,
                "sort_direction": direction,
                "sort_links": sort_links,
                "log_view": log_view,
                "query_string": query_params.urlencode(),
                "can_export_audit_log": has_role(request.user, (ROLE_ADMINISTRATOR,)),
            },
        )

    def decorate_entry(self, entry: AuditLog, command: BarrierCommand | None = None) -> None:
        details = entry.details or {}
        entry.action_label = self.action_labels.get(
            entry.action, entry.action.replace("_", " ").capitalize()
        )
        entry.action_icon = (
            "🔓"
            if entry.action in {"manual_barrier_command_requested", "emergency_barrier_command_requested"}
            else "🔒"
            if entry.action in {"barrier_closed_automatically", "barrier_closed_manually"}
            else ""
        )
        entry.event_id = details.get("event_id")
        entry.command_id = details.get("command_id")
        entry.is_independent_command = (
            (command is not None and command.decision_id is None)
            or entry.action == "emergency_barrier_command_requested"
        )
        entry.command_label = (
            f"Barrier control #{entry.command_id}"
            if entry.is_independent_command
            else f"Barrier command #{entry.command_id}"
        )
        entry.is_indefinite_opening = (
            details.get("opening_mode") == "indefinite"
            or (
                entry.action == "barrier_closed_manually"
                and command is not None
                and command.auto_close_at is None
            )
        )
        entry.is_event_linked_opening = (
            entry.action == "manual_barrier_command_requested" and bool(entry.event_id)
        )
        entry.is_independent_opening = (
            entry.action == "emergency_barrier_command_requested"
            or (
                entry.action == "barrier_closed_manually"
                and command is not None
                and command.decision_id is None
            )
        )
        detail_labels = {
            "auto_close_at": "Auto-close",
            "auto_close_seconds": "Close after",
            "count": "Count",
            "change_summary": "Changes",
            "gate_name": "Gate",
            "manual_comment": "Comment",
            "manual_reason_label": "Reason",
            "opening_mode": "Opening mode",
            "object_label": "Record",
            "path": "Path",
            "purged_before": "Purged before",
            "request_reference": "Request",
            "resource_label": "Configuration",
            "username": "Username",
        }
        entry.detail_lines = []
        for key, value in details.items():
            if key not in detail_labels or value in (None, ""):
                continue
            if key == "auto_close_at":
                try:
                    value = timezone.localtime(datetime.fromisoformat(value)).strftime(
                        "%Y-%m-%d %H:%M:%S %Z"
                    )
                except (TypeError, ValueError):
                    pass
            entry.detail_lines.append(f"{detail_labels[key]}: {value}")


class ActivityLogExportView(ActivityLogView):
    allowed_roles = (ROLE_ADMINISTRATOR,)

    def get(self, request: HttpRequest) -> JsonResponse:
        entries, _, _, _ = self.filtered_entries(request)
        response = JsonResponse(
            [
                {
                    "id": entry.pk,
                    "time": entry.created_at.isoformat(),
                    "action": entry.action,
                    "actor": entry.actor.username if entry.actor else None,
                    "ip_address": entry.ip_address,
                    "details": entry.details,
                }
                for entry in entries
            ],
            safe=False,
            json_dumps_params={"ensure_ascii": False, "indent": 2},
        )
        response["Content-Disposition"] = (
            f'attachment; filename="cerberus-activity-log-{timezone.localdate():%Y-%m-%d}.json"'
        )
        return response


class BarrierCommandDetailView(OperatorAccessMixin, DetailView):
    model = BarrierCommand
    template_name = "domain/operator/barrier_command_detail.html"
    context_object_name = "command"

    def get_queryset(self) -> QuerySet[BarrierCommand]:
        return BarrierCommand.objects.select_related("gate__site", "requested_by", "decision__event")

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        context = super().get_context_data(**kwargs)
        context["reason_label"] = dict(ManualBarrierOpenForm.REASON_CHOICES).get(
            self.object.manual_reason, self.object.manual_reason or "—"
        )
        context["audit_history"] = AuditLog.objects.filter(details__command_id=self.object.pk)
        return context


class ResourceManagementView(OperatorAccessMixin, View):
    template_name = "domain/operator/management.html"

    def get_config(self, resource: str) -> tuple[type[Any], type[Any], str, str] | None:
        return RESOURCE_CONFIG.get(resource)

    @staticmethod
    def can_manage(request: HttpRequest) -> bool:
        return has_role(request.user, (ROLE_ADMINISTRATOR, ROLE_MANAGER))

    @staticmethod
    def can_view_resource(request: HttpRequest, resource: str) -> bool:
        if resource == "retention":
            return has_role(request.user, (ROLE_ADMINISTRATOR,))
        return True

    @staticmethod
    def get_singleton(resource: str, model: type[Any]) -> Any | None:
        defaults = SINGLETON_RESOURCE_DEFAULTS.get(resource)
        if defaults is None:
            return None
        settings_record, _ = model.objects.get_or_create(pk=1, defaults=defaults())
        return settings_record

    def get(self, request: HttpRequest, resource: str) -> HttpResponse:
        config = self.get_config(resource)
        if config is None:
            return HttpResponseForbidden("Unknown management resource.")
        if not self.can_view_resource(request, resource):
            return HttpResponseForbidden("Administrator role is required to view data retention.")
        model, form_class, title, item_label = config
        singleton = self.get_singleton(resource, model)
        form = form_class(instance=singleton) if self.can_manage(request) else None
        items = model.objects.filter(pk=singleton.pk) if singleton else model.objects.all()
        return self.render_form(request, items, form, title, item_label, singleton)

    def post(self, request: HttpRequest, resource: str) -> HttpResponse:
        if not self.can_manage(request):
            return HttpResponseForbidden("Manager role is required to change configuration.")
        config = self.get_config(resource)
        if config is None:
            return HttpResponseForbidden("Unknown management resource.")
        if not self.can_view_resource(request, resource):
            return HttpResponseForbidden("Administrator role is required to view data retention.")
        model, form_class, title, item_label = config
        singleton = self.get_singleton(resource, model)
        form = form_class(request.POST, instance=singleton)
        if form.is_valid():
            created = form.instance._state.adding
            item = form.save()
            if created or form.changed_data:
                record_configuration_change(
                    request=request,
                    form=form,
                    resource=resource,
                    title=title,
                    item=item,
                    created=created,
                )
            messages.success(request, f"{item_label.capitalize()} saved.")
            return redirect("manage-resource", resource=resource)
        items = model.objects.filter(pk=singleton.pk) if singleton else model.objects.all()
        return self.render_form(request, items, form, title, item_label, singleton)

    def render_form(
        self,
        request: HttpRequest,
        items: QuerySet[Any],
        form: Any | None,
        title: str,
        item_label: str,
        singleton: Any | None,
    ) -> HttpResponse:
        return render(
            request,
            self.template_name,
            {
                "items": items,
                "form": form,
                "title": title,
                "item_label": item_label,
                "resource": self.kwargs["resource"],
                "resource_description": RESOURCE_DESCRIPTIONS[self.kwargs["resource"]],
                "can_manage": self.can_manage(request),
                "can_view_retention": has_role(request.user, (ROLE_ADMINISTRATOR,)),
                "singleton": singleton,
                "is_singleton_config": singleton is not None,
            },
        )


class ResourceUpdateView(OperatorAccessMixin, View):
    template_name = "domain/operator/edit.html"

    def get_config(self, resource: str) -> tuple[type[Any], type[Any], str, str] | None:
        return RESOURCE_CONFIG.get(resource)

    def get(self, request: HttpRequest, resource: str, pk: int) -> HttpResponse:
        if not ResourceManagementView.can_view_resource(request, resource):
            return HttpResponseForbidden("Administrator role is required to view data retention.")
        if resource in SINGLETON_RESOURCE_DEFAULTS:
            return redirect("manage-resource", resource=resource)
        config = self.get_config(resource)
        if config is None:
            return HttpResponseForbidden("Unknown management resource.")
        model, form_class, title, _ = config
        item = get_object_or_404(model, pk=pk)
        if not ResourceManagementView.can_manage(request):
            return render(
                request,
                "domain/operator/resource_detail.html",
                {"title": title, "resource": resource, "item": item},
            )
        return render(
            request,
            self.template_name,
            {"form": form_class(instance=item), "title": title, "resource": resource, "item": item},
        )

    def post(self, request: HttpRequest, resource: str, pk: int) -> HttpResponse:
        if not ResourceManagementView.can_view_resource(request, resource):
            return HttpResponseForbidden("Administrator role is required to view data retention.")
        if resource in SINGLETON_RESOURCE_DEFAULTS:
            return redirect("manage-resource", resource=resource)
        if not ResourceManagementView.can_manage(request):
            return HttpResponseForbidden("Manager role is required to change configuration.")
        config = self.get_config(resource)
        if config is None:
            return HttpResponseForbidden("Unknown management resource.")
        model, form_class, title, _ = config
        item = get_object_or_404(model, pk=pk)
        form = form_class(request.POST, instance=item)
        if form.is_valid():
            form.save()
            if form.changed_data:
                record_configuration_change(
                    request=request,
                    form=form,
                    resource=resource,
                    title=title,
                    item=item,
                    created=False,
                )
            messages.success(request, "Changes saved.")
            return redirect("manage-resource", resource=resource)
        return render(
            request,
            self.template_name,
            {"form": form, "title": title, "resource": resource, "item": item},
        )
