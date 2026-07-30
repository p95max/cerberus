"""FastAPI application for the internal Janus recognition service."""

from __future__ import annotations

import asyncio
import json
import logging
import secrets
import time
import uuid
from collections.abc import Awaitable, Callable

from fastapi import Depends, FastAPI, File, Header, HTTPException, Request, UploadFile, status
from starlette.responses import Response

from janus_service.recognition import PlaceholderRecognitionEngine, RecognitionResult
from janus_service.schemas import RecognitionResponse
from janus_service.settings import settings

VERSION = "0.1.0"
ALLOWED_IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp"}
logger = logging.getLogger("janus")


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        for field in ("request_id", "method", "path", "status_code", "duration_ms"):
            value = getattr(record, field, None)
            if value is not None:
                payload[field] = value
        return json.dumps(payload, ensure_ascii=False)


def configure_logging() -> None:
    if logger.handlers:
        return
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False


configure_logging()
app = FastAPI(title="Janus recognition service", version=VERSION)
engine = PlaceholderRecognitionEngine()


@app.middleware("http")
async def request_context(request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
    request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
    request.state.request_id = request_id
    started = time.monotonic()
    response = await call_next(request)
    response.headers["X-Request-ID"] = request_id
    logger.info(
        "request completed",
        extra={
            "request_id": request_id,
            "method": request.method,
            "path": request.url.path,
            "status_code": response.status_code,
            "duration_ms": round((time.monotonic() - started) * 1000),
        },
    )
    return response


def require_service_authentication(x_api_key: str | None = Header(default=None)) -> None:
    if x_api_key is None or not secrets.compare_digest(x_api_key, settings.api_key):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid service credentials.")


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/readyz")
async def readyz() -> dict[str, str]:
    return {"status": "ready"}


@app.get("/version")
async def version() -> dict[str, str]:
    return {"service": "janus", "version": VERSION, "environment": settings.environment}


@app.post(
    "/api/v1/recognize",
    response_model=RecognitionResponse,
    dependencies=[Depends(require_service_authentication)],
)
async def recognize(
    request: Request,
    image: UploadFile = File(...),
    recognition_request_id: str = Header(..., alias="X-Recognition-Request-ID"),
) -> RecognitionResponse:
    """Recognize a plate image without making an access decision."""
    if image.content_type not in ALLOWED_IMAGE_TYPES:
        raise HTTPException(status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, detail="Unsupported image type.")

    image_bytes = await image.read(settings.max_file_size_bytes + 1)
    if len(image_bytes) > settings.max_file_size_bytes:
        raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail="Image is too large.")

    started = time.monotonic()
    try:
        result: RecognitionResult = await asyncio.wait_for(
            engine.recognize(image_bytes, image.content_type),
            timeout=settings.processing_timeout_seconds,
        )
    except TimeoutError as error:
        raise HTTPException(status_code=status.HTTP_504_GATEWAY_TIMEOUT, detail="Recognition timed out.") from error

    return RecognitionResponse(
        recognition_request_id=recognition_request_id,
        status=result.status,
        candidates=result.candidates,
        processing_time_ms=round((time.monotonic() - started) * 1000),
        bounding_boxes=result.bounding_boxes,
    )
