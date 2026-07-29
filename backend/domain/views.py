from __future__ import annotations

from typing import Any

from django.conf import settings
from django.http import HttpRequest
from drf_spectacular.utils import OpenApiExample, extend_schema
from rest_framework import exceptions, status
from rest_framework.parsers import JSONParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from accounts.audit import record_audit
from accounts.authentication import ServiceKeyAuthentication
from domain.serializers import RecognitionEventRequestSerializer, RecognitionEventResponseSerializer
from domain.services.recognition import submit_recognition_event


@extend_schema(
    request=RecognitionEventRequestSerializer,
    responses={200: RecognitionEventResponseSerializer, 201: RecognitionEventResponseSerializer},
    examples=[
        OpenApiExample(
            "Recognition event",
            value={
                "recognition_request_id": "a3f2c5f8-f2ae-4ac4-a13f-9b8a6b489e64",
                "plate_number": "A 123 BC 77",
                "confidence": "0.9900",
                "camera_external_id": "north-entry-camera",
                "direction": "entry",
                "captured_at": "2026-07-29T09:30:00Z",
                "image_metadata": {"frame_id": "frame-42", "mime_type": "image/jpeg"},
            },
            request_only=True,
        ),
        OpenApiExample(
            "Decision response",
            value={
                "event_id": 42,
                "normalized_plate": "A123BC77",
                "decision": "allow",
                "reason": "Matched whitelist access rule 12.",
            },
            response_only=True,
            status_codes=["201", "200"],
        ),
    ],
)
class RecognitionEventAPIView(APIView):
    authentication_classes: list[type[Any]] = [ServiceKeyAuthentication]
    permission_classes = [IsAuthenticated]
    parser_classes = [JSONParser]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "service"

    def post(self, request: HttpRequest) -> Response:
        content_length = int(request.META.get("CONTENT_LENGTH") or 0)
        if content_length > settings.RECOGNITION_EVENT_MAX_BYTES:
            raise exceptions.ParseError("Recognition event request is too large.")

        serializer = RecognitionEventRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        submission = submit_recognition_event(
            submitted_by=request.user,
            **serializer.validated_data,
        )
        body = {
            "event_id": submission.event.pk,
            "normalized_plate": submission.event.normalized_plate,
            "decision": submission.decision.outcome,
            "reason": submission.decision.reason,
        }
        if submission.created:
            record_audit(
                "recognition_event_received",
                request=request,
                actor=request.user,
                details={"event_id": submission.event.pk, "decision": submission.decision.outcome},
            )
        return Response(
            body, status=status.HTTP_201_CREATED if submission.created else status.HTTP_200_OK
        )
