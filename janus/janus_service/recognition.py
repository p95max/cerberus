"""Recognition-engine boundary.

Janus never makes an access decision. The Phase 11 mock engine makes the API
demonstrable until an OCR provider is connected behind the same interface.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from janus_service.schemas import BoundingBox, PlateCandidate, RecognitionStatus


@dataclass(frozen=True)
class RecognitionResult:
    status: RecognitionStatus
    candidates: list[PlateCandidate]
    bounding_boxes: list[BoundingBox]


class MockRecognitionEngine:
    """Deterministic development recognizer selected from an uploaded filename.

    Use ``recognized-A123BC77.png`` or ``uncertain-A123BC77.png`` to return one
    candidate. Any other filename returns ``not_detected``. This gives the API a
    repeatable demo contract without pretending that OCR has happened.
    """

    async def recognize(
        self, image: bytes, content_type: str, filename: str | None
    ) -> RecognitionResult:
        del image, content_type
        stem = Path(filename or "").stem
        mode, separator, plate = stem.partition("-")
        plate = plate.upper()
        if mode == "recognized" and separator and plate:
            bounding_box = BoundingBox(x=80, y=60, width=260, height=80)
            return RecognitionResult(
                status=RecognitionStatus.RECOGNIZED,
                candidates=[
                    PlateCandidate(plate=plate, confidence=0.98, bounding_box=bounding_box)
                ],
                bounding_boxes=[bounding_box],
            )
        if mode == "uncertain" and separator and plate:
            bounding_box = BoundingBox(x=80, y=60, width=260, height=80)
            return RecognitionResult(
                status=RecognitionStatus.UNCERTAIN,
                candidates=[
                    PlateCandidate(plate=plate, confidence=0.55, bounding_box=bounding_box)
                ],
                bounding_boxes=[bounding_box],
            )
        return RecognitionResult(
            status=RecognitionStatus.NOT_DETECTED,
            candidates=[],
            bounding_boxes=[],
        )
