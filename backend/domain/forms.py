from __future__ import annotations

from django import forms

from domain.models import (
    AccessList,
    AccessRule,
    BarrierControlSettings,
    Camera,
    Gate,
    ParkingSite,
    RecognitionRetentionPolicy,
    Vehicle,
)


class ManualBarrierOpenForm(forms.Form):
    REASON_CHOICES = (
        ("vip_person", "VIP person"),
        ("emergency_services", "Emergency services (ambulance, fire, police)"),
        ("fire_evacuation", "Fire or evacuation"),
        ("verified_visitor", "Verified visitor"),
        ("recognition_error", "Recognition error"),
        ("other", "Other"),
    )

    reason = forms.ChoiceField(choices=REASON_CHOICES)
    comment = forms.CharField(
        max_length=500,
        required=False,
        widget=forms.Textarea(attrs={"rows": 3, "placeholder": "Optional details"}),
    )


class EmergencyBarrierOpenForm(ManualBarrierOpenForm):
    gate = forms.ModelChoiceField(
        queryset=Gate.objects.filter(is_active=True).select_related("site"),
        label="Gate",
    )
    request_reference = forms.CharField(max_length=120, label="Request or ticket number")


class ParkingSiteForm(forms.ModelForm):
    class Meta:
        model = ParkingSite
        fields = ("external_id", "name", "address", "is_active")


class GateForm(forms.ModelForm):
    class Meta:
        model = Gate
        fields = ("site", "external_id", "name", "direction", "is_active")


class CameraForm(forms.ModelForm):
    class Meta:
        model = Camera
        fields = ("gate", "external_id", "name", "is_active")


class VehicleForm(forms.ModelForm):
    class Meta:
        model = Vehicle
        fields = ("normalized_plate", "display_plate", "owner_name", "is_active")


class AccessListForm(forms.ModelForm):
    class Meta:
        model = AccessList
        fields = ("site", "name", "kind", "is_active")


class AccessRuleForm(forms.ModelForm):
    class Meta:
        model = AccessRule
        fields = (
            "access_list",
            "vehicle",
            "gate",
            "decision",
            "priority",
            "valid_from",
            "valid_until",
            "allowed_weekdays",
            "allowed_from_time",
            "allowed_until_time",
            "is_active",
        )
        widgets = {
            "valid_from": forms.DateTimeInput(attrs={"type": "datetime-local"}),
            "valid_until": forms.DateTimeInput(attrs={"type": "datetime-local"}),
            "allowed_from_time": forms.TimeInput(attrs={"type": "time"}),
            "allowed_until_time": forms.TimeInput(attrs={"type": "time"}),
            "allowed_weekdays": forms.TextInput(attrs={"placeholder": "[0, 1, 2, 3, 4]"}),
        }


class RecognitionRetentionPolicyForm(forms.ModelForm):
    class Meta:
        model = RecognitionRetentionPolicy
        fields = (
            "image_metadata_enabled",
            "image_metadata_retention_days",
            "event_retention_enabled",
            "event_retention_days",
            "aggregate_audit_retention_enabled",
            "aggregate_audit_retention_days",
        )
        labels = {
            "image_metadata_enabled": "Clear image metadata",
            "image_metadata_retention_days": "Image metadata retention (days)",
            "event_retention_enabled": "Delete full recognition events",
            "event_retention_days": "Full-event retention (days)",
            "aggregate_audit_retention_enabled": "Delete aggregate cleanup audits",
            "aggregate_audit_retention_days": "Aggregate-audit retention (days)",
        }


class BarrierControlSettingsForm(forms.ModelForm):
    class Meta:
        model = BarrierControlSettings
        fields = ("auto_close_seconds",)
        labels = {"auto_close_seconds": "Automatic close delay (seconds)"}
