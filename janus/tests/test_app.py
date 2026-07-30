from fastapi.testclient import TestClient
import pytest

from janus_service.app import app
from janus_service.schemas import RecognitionResponse, RecognitionStatus
from janus_service.settings import settings

client = TestClient(app)
AUTH_HEADERS = {"X-API-Key": settings.api_key}


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
        headers={**AUTH_HEADERS, "X-Recognition-Request-ID": "request-123", "X-Request-ID": "trace-123"},
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


def test_recognition_rejects_unsupported_image_types() -> None:
    response = client.post(
        "/api/v1/recognize",
        headers={**AUTH_HEADERS, "X-Recognition-Request-ID": "request-123"},
        files={"image": ("vehicle.txt", b"not an image", "text/plain")},
    )

    assert response.status_code == 415


def test_recognition_status_schema_includes_all_contract_states() -> None:
    assert {status.value for status in RecognitionStatus} == {"recognized", "uncertain", "not_detected"}
