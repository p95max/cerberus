from __future__ import annotations

import json
from typing import Any

from django.utils import timezone
from rest_framework import serializers

from domain.models import Gate
from domain.services.decisions import normalize_plate


class RecognitionEventRequestSerializer(serializers.Serializer):
    recognition_request_id = serializers.UUIDField()
    plate_number = serializers.CharField(max_length=64, trim_whitespace=True)
    confidence = serializers.DecimalField(max_digits=5, decimal_places=4, min_value=0, max_value=1)
    camera_external_id = serializers.CharField(max_length=64)
    direction = serializers.ChoiceField(choices=Gate.Direction.choices)
    captured_at = serializers.DateTimeField()
    image_metadata = serializers.JSONField(required=False, default=dict)

    def validate_plate_number(self, value: str) -> str:
        if not normalize_plate(value):
            raise serializers.ValidationError("Plate number must contain letters or digits.")
        return value

    def validate_captured_at(self, value: Any) -> Any:
        if timezone.is_naive(value):
            raise serializers.ValidationError("captured_at must include a timezone offset.")
        return value

    def validate_image_metadata(self, value: Any) -> dict[str, Any]:
        if not isinstance(value, dict):
            raise serializers.ValidationError("image_metadata must be an object.")
        if len(json.dumps(value, separators=(",", ":"))) > 4096:
            raise serializers.ValidationError("image_metadata must not exceed 4 KiB.")
        if {"image", "image_base64", "data"}.intersection(value):
            raise serializers.ValidationError("Raw image data is not accepted; send metadata only.")
        return value


class RecognitionEventResponseSerializer(serializers.Serializer):
    event_id = serializers.IntegerField()
    normalized_plate = serializers.CharField()
    decision = serializers.CharField()
    reason = serializers.CharField()
