from __future__ import annotations

from datetime import datetime
from typing import Any, ClassVar

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.auth.views import LoginView, LogoutView
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
    CameraForm,
    GateForm,
    ParkingSiteForm,
    VehicleForm,
)
from domain.models import (
    AccessDecision,
    AccessList,
    AccessRule,
    BarrierCommand,
    Camera,
    Gate,
    ParkingSite,
    RecognitionEvent,
    Vehicle,
)


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
            request, filtered_events(request)[:100], "Recent recognition events"
        )

    def render_events(
        self, request: HttpRequest, events: QuerySet[RecognitionEvent], title: str
    ) -> HttpResponse:
        return render(
            request,
            self.template_name,
            {
                "events": events,
                "title": title,
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
        return self.render_events(request, events[:100], "Manual review queue")


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
        command = BarrierCommand.objects.create(
            decision=event.decision,
            gate=event.camera.gate,
            requested_by=request.user,
        )
        record_audit(
            "manual_barrier_command_requested",
            request=request,
            actor=request.user,
            details={"event_id": event.pk, "command_id": command.pk},
        )
        messages.success(request, "Barrier command queued for the mock controller.")
        return redirect("operator-event-detail", pk=event.pk)


RESOURCE_CONFIG: dict[str, tuple[type[Any], type[Any], str]] = {
    "sites": (ParkingSite, ParkingSiteForm, "Parking sites"),
    "gates": (Gate, GateForm, "Gates"),
    "cameras": (Camera, CameraForm, "Cameras"),
    "vehicles": (Vehicle, VehicleForm, "Vehicles"),
    "access-lists": (AccessList, AccessListForm, "Access lists"),
    "access-rules": (AccessRule, AccessRuleForm, "Access rules"),
}


class ManagerAccessMixin(OperatorAccessMixin):
    allowed_roles = (ROLE_ADMINISTRATOR, ROLE_MANAGER)


class ResourceManagementView(ManagerAccessMixin, View):
    template_name = "domain/operator/management.html"

    def get_config(self, resource: str) -> tuple[type[Any], type[Any], str] | None:
        return RESOURCE_CONFIG.get(resource)

    def get(self, request: HttpRequest, resource: str) -> HttpResponse:
        config = self.get_config(resource)
        if config is None:
            return HttpResponseForbidden("Unknown management resource.")
        model, form_class, title = config
        return self.render_form(request, model.objects.all(), form_class(), title)

    def post(self, request: HttpRequest, resource: str) -> HttpResponse:
        config = self.get_config(resource)
        if config is None:
            return HttpResponseForbidden("Unknown management resource.")
        model, form_class, title = config
        form = form_class(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, f"{title[:-1]} saved.")
            return redirect("manage-resource", resource=resource)
        return self.render_form(request, model.objects.all(), form, title)

    def render_form(
        self, request: HttpRequest, items: QuerySet[Any], form: Any, title: str
    ) -> HttpResponse:
        return render(
            request,
            self.template_name,
            {"items": items, "form": form, "title": title, "resource": self.kwargs["resource"]},
        )


class ResourceUpdateView(ManagerAccessMixin, View):
    template_name = "domain/operator/edit.html"

    def get_config(self, resource: str) -> tuple[type[Any], type[Any], str] | None:
        return RESOURCE_CONFIG.get(resource)

    def get(self, request: HttpRequest, resource: str, pk: int) -> HttpResponse:
        config = self.get_config(resource)
        if config is None:
            return HttpResponseForbidden("Unknown management resource.")
        model, form_class, title = config
        item = get_object_or_404(model, pk=pk)
        return render(
            request,
            self.template_name,
            {"form": form_class(instance=item), "title": title, "resource": resource, "item": item},
        )

    def post(self, request: HttpRequest, resource: str, pk: int) -> HttpResponse:
        config = self.get_config(resource)
        if config is None:
            return HttpResponseForbidden("Unknown management resource.")
        model, form_class, title = config
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
