import pytest
from fastapi.testclient import TestClient

import janus_service.app as app_module
from janus_service.app import app
from janus_service.recognition import MockRecognitionEngine, recognition_result_from_tesseract_data
from janus_service.schemas import BoundingBox, RecognitionResponse, RecognitionStatus
from janus_service.settings import settings

client = TestClient(app)
AUTH_HEADERS = {"X-API-Key": settings.api_key}


@pytest.fixture(autouse=True)
def use_mock_engine_for_api_contract_tests(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep API-contract tests independent from the configured runtime OCR backend."""
    monkeypatch.setattr(app_module, "engine", MockRecognitionEngine())


def test_health_readiness_and_version_endpoints() -> None:
    assert client.get("/healthz").json() == {"status": "ok"}
    assert client.get("/readyz").json() == {"status": "ready"}
    assert client.get("/version").json()["service"] == "janus"


def test_recognition_requires_service_authentication() -> None:
    response = client.post("/api/v1/recognize")

    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid service credentials."


def test_recognition_returns_not_detected_for_an_unmapped_file() -> None:
    response = client.post(
        "/api/v1/recognize",
        headers={
            **AUTH_HEADERS,
            "X-Recognition-Request-ID": "request-123",
            "X-Request-ID": "trace-123",
        },
        files={"image": ("vehicle.png", b"image-bytes", "image/png")},
    )

    assert response.status_code == 200
    assert response.headers["X-Request-ID"] == "trace-123"
    payload = RecognitionResponse.model_validate(response.json())
    assert payload.recognition_request_id == "request-123"
    assert payload.status is RecognitionStatus.NOT_DETECTED
    assert payload.candidates == []
    assert payload.bounding_boxes == []


@pytest.mark.parametrize(
    ("filename", "expected_status", "expected_confidence"),
    [
        ("recognized-A123BC77.png", RecognitionStatus.RECOGNIZED, 0.98),
        ("uncertain-A123BC77.png", RecognitionStatus.UNCERTAIN, 0.55),
    ],
)
def test_mock_recognition_returns_repeatable_candidates(
    filename: str, expected_status: RecognitionStatus, expected_confidence: float
) -> None:
    response = client.post(
        "/api/v1/recognize",
        headers={**AUTH_HEADERS, "X-Recognition-Request-ID": "request-123"},
        files={"image": (filename, b"image-bytes", "image/png")},
    )

    payload = RecognitionResponse.model_validate(response.json())
    assert payload.status is expected_status
    assert payload.candidates[0].plate == "A123BC77"
    assert payload.candidates[0].confidence == expected_confidence
    assert payload.bounding_boxes == [payload.candidates[0].bounding_box]


def test_tesseract_result_parser_returns_cropped_plate_candidates() -> None:
    result = recognition_result_from_tesseract_data(
        {
            "text": ["A123BC77", ""],
            "conf": ["91.5", "-1"],
            "left": [12, 0],
            "top": [8, 0],
            "width": [180, 0],
            "height": [42, 0],
        }
    )

    assert result.status is RecognitionStatus.RECOGNIZED
    assert result.candidates[0].plate == "A123BC77"
    assert result.candidates[0].confidence == 0.915
    assert result.candidates[0].bounding_box == BoundingBox(
        x=12, y=8, width=180, height=42
    )


def test_tesseract_result_parser_returns_not_detected_without_valid_words() -> None:
    result = recognition_result_from_tesseract_data(
        {
            "text": [""],
            "conf": ["-1"],
            "left": [0],
            "top": [0],
            "width": [0],
            "height": [0],
        }
    )

    assert result.status is RecognitionStatus.NOT_DETECTED


def test_recognition_rejects_unsupported_image_types() -> None:
    response = client.post(
        "/api/v1/recognize",
        headers={**AUTH_HEADERS, "X-Recognition-Request-ID": "request-123"},
        files={"image": ("vehicle.txt", b"not an image", "text/plain")},
    )

    assert response.status_code == 415


def test_recognition_status_schema_includes_all_contract_states() -> None:
    assert {status.value for status in RecognitionStatus} == {
        "recognized",
        "uncertain",
        "not_detected",
    }
