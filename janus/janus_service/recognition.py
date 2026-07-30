"""Recognition-engine boundary.

Phase 10 establishes the stable Janus contract. OCR/ANPR providers are added behind
this boundary in later phases; Janus never makes an access decision itself.
"""

from __future__ import annotations

from dataclasses import dataclass

from janus_service.schemas import BoundingBox, PlateCandidate, RecognitionStatus


@dataclass(frozen=True)
class RecognitionResult:
    status: RecognitionStatus
    candidates: list[PlateCandidate]
    bounding_boxes: list[BoundingBox]


class PlaceholderRecognitionEngine:
    """Safe default until an OCR provider is configured."""

    async def recognize(self, image: bytes, content_type: str) -> RecognitionResult:
        del image, content_type
        return RecognitionResult(
            status=RecognitionStatus.NOT_DETECTED,
            candidates=[],
            bounding_boxes=[],
        )
