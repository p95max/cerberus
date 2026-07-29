from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, ClassVar

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.auth.views import LoginView, LogoutView
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import QuerySet
from django.http import HttpRequest, HttpResponse, HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views import View
from django.views.generic import DetailView

from accounts.audit import record_audit
from accounts.models import AuditLog
from accounts.roles import ROLE_ADMINISTRATOR, ROLE_MANAGER, ROLE_OPERATOR, ROLE_READ_ONLY, has_role
from domain.forms import (
    AccessListForm,
    AccessRuleForm,
    BarrierControlSettingsForm,
    CameraForm,
    GateForm,
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
            },
        )


class ManualReviewQueueView(OperatorDashboardView):
    def get(self, request: HttpRequest) -> HttpResponse:
        events = filtered_events(request).filter(
            decision__outcome=AccessDecision.Outcome.MANUAL_REVIEW
        )
        return self.render_events(request, events, "Manual review queue", "🔎")


class EventDetailView(OperatorAccessMixin, DetailView):
    model = RecognitionEvent
    template_name = "domain/operator/event_detail.html"
    context_object_name = "event"

    def get_queryset(self) -> QuerySet[RecognitionEvent]:
        return RecognitionEvent.objects.select_related(
            "camera__gate__site", "decision__matched_rule"
        )

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        context = super().get_context_data(**kwargs)
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
        if request.POST.get("action") != "open":
            messages.error(request, "Choose Open to queue a manual barrier command.")
            return redirect("operator-event-detail", pk=event.pk)
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
        command = BarrierCommand.objects.create(
            decision=event.decision,
            gate=event.camera.gate,
            requested_by=request.user,
            auto_close_at=auto_close_at,
        )
        record_audit(
            "manual_barrier_command_requested",
            request=request,
            actor=request.user,
            details={
                "event_id": event.pk,
                "command_id": command.pk,
                "auto_close_at": auto_close_at.isoformat(),
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

SINGLETON_RESOURCE_DEFAULTS = {
    "retention": retention_policy_defaults,
    "barrier": barrier_control_defaults,
}


class ManagerAccessMixin(OperatorAccessMixin):
    allowed_roles = (ROLE_ADMINISTRATOR, ROLE_MANAGER)


class ResourceManagementView(OperatorAccessMixin, View):
    template_name = "domain/operator/management.html"

    def get_config(self, resource: str) -> tuple[type[Any], type[Any], str, str] | None:
        return RESOURCE_CONFIG.get(resource)

    @staticmethod
    def can_manage(request: HttpRequest) -> bool:
        return has_role(request.user, (ROLE_ADMINISTRATOR, ROLE_MANAGER))

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
        model, form_class, title, item_label = config
        singleton = self.get_singleton(resource, model)
        form = form_class(request.POST, instance=singleton)
        if form.is_valid():
            form.save()
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
                "can_manage": self.can_manage(request),
                "singleton": singleton,
                "is_singleton_config": singleton is not None,
            },
        )


class ResourceUpdateView(OperatorAccessMixin, View):
    template_name = "domain/operator/edit.html"

    def get_config(self, resource: str) -> tuple[type[Any], type[Any], str, str] | None:
        return RESOURCE_CONFIG.get(resource)

    def get(self, request: HttpRequest, resource: str, pk: int) -> HttpResponse:
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
            messages.success(request, "Changes saved.")
            return redirect("manage-resource", resource=resource)
        return render(
            request,
            self.template_name,
            {"form": form, "title": title, "resource": resource, "item": item},
        )
