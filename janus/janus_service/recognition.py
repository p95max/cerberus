"""Recognition-engine boundary.

Janus never makes an access decision. The Phase 11 mock engine makes the API
demonstrable until an OCR provider is connected behind the same interface.
"""

from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import Protocol

from janus_service.schemas import BoundingBox, PlateCandidate, RecognitionStatus


@dataclass(frozen=True)
class RecognitionResult:
    status: RecognitionStatus
    candidates: list[PlateCandidate]
    bounding_boxes: list[BoundingBox]


class RecognitionEngine(Protocol):
    async def recognize(
        self, image: bytes, content_type: str, filename: str | None
    ) -> RecognitionResult: ...


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


class TesseractRecognitionEngine:
    """OCR for an image that already contains one cropped licence plate."""

    async def recognize(
        self, image: bytes, content_type: str, filename: str | None
    ) -> RecognitionResult:
        del content_type, filename
        try:
            from PIL import Image
            import pytesseract  # type: ignore[import-untyped]
        except ImportError as error:  # pragma: no cover - guarded by the image build
            raise RuntimeError("Tesseract OCR dependencies are not installed") from error

        with Image.open(BytesIO(image)) as plate_image:
            data = pytesseract.image_to_data(
                plate_image,
                config="--psm 7 -c tessedit_char_whitelist=ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789",
                output_type=pytesseract.Output.DICT,
            )
        return recognition_result_from_tesseract_data(data)


def recognition_result_from_tesseract_data(data: dict[str, list[object]]) -> RecognitionResult:
    """Build the versioned response from Tesseract's word-level output."""
    candidates: list[PlateCandidate] = []
    bounding_boxes: list[BoundingBox] = []
    texts = data.get("text", [])
    confidences = data.get("conf", [])
    lefts = data.get("left", [])
    tops = data.get("top", [])
    widths = data.get("width", [])
    heights = data.get("height", [])
    for text, confidence, left, top, width, height in zip(
        texts, confidences, lefts, tops, widths, heights, strict=True
    ):
        plate = str(text).strip().replace(" ", "").upper()
        try:
            confidence_value = float(str(confidence)) / 100
            bounding_box = BoundingBox(
                x=int(str(left)),
                y=int(str(top)),
                width=int(str(width)),
                height=int(str(height)),
            )
        except (TypeError, ValueError):
            continue
        if (
            not plate
            or confidence_value < 0
            or bounding_box.width <= 0
            or bounding_box.height <= 0
        ):
            continue
        candidates.append(
            PlateCandidate(
                plate=plate,
                confidence=min(confidence_value, 1),
                bounding_box=bounding_box,
            )
        )
        bounding_boxes.append(bounding_box)

    if not candidates:
        return RecognitionResult(
            status=RecognitionStatus.NOT_DETECTED,
            candidates=[],
            bounding_boxes=[],
        )
    return RecognitionResult(
        status=RecognitionStatus.RECOGNIZED,
        candidates=candidates,
        bounding_boxes=bounding_boxes,
    )


def build_recognition_engine(backend: str) -> RecognitionEngine:
    if backend == "mock":
        return MockRecognitionEngine()
    if backend == "tesseract":
        return TesseractRecognitionEngine()
    raise ValueError(f"Unsupported recognition backend: {backend}")
