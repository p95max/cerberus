"""Versioned API schemas exposed by Janus."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field


class RecognitionStatus(StrEnum):
    RECOGNIZED = "recognized"
    UNCERTAIN = "uncertain"
    NOT_DETECTED = "not_detected"


class BoundingBox(BaseModel):
    x: int = Field(ge=0)
    y: int = Field(ge=0)
    width: int = Field(gt=0)
    height: int = Field(gt=0)


class PlateCandidate(BaseModel):
    plate: str = Field(min_length=1, max_length=32)
    confidence: float = Field(ge=0, le=1)
    bounding_box: BoundingBox | None = None


class RecognitionResponse(BaseModel):
    recognition_request_id: str = Field(min_length=1, max_length=128)
    status: RecognitionStatus
    candidates: list[PlateCandidate]
    processing_time_ms: int = Field(ge=0)
    bounding_boxes: list[BoundingBox]
