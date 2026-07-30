"""Environment-backed settings for Janus."""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    environment: str
    api_key: str
    recognition_backend: str
    opencv_upscale_factor: float
    max_file_size_bytes: int
    processing_timeout_seconds: float

    @classmethod
    def from_environment(cls) -> Settings:
        max_file_size_bytes = int(os.getenv("JANUS_MAX_FILE_SIZE_BYTES", "10485760"))
        processing_timeout_seconds = float(os.getenv("JANUS_PROCESSING_TIMEOUT_SECONDS", "5"))
        opencv_upscale_factor = float(os.getenv("JANUS_OPENCV_UPSCALE_FACTOR", "2"))
        if max_file_size_bytes <= 0:
            raise ValueError("JANUS_MAX_FILE_SIZE_BYTES must be positive")
        if processing_timeout_seconds <= 0:
            raise ValueError("JANUS_PROCESSING_TIMEOUT_SECONDS must be positive")
        if opencv_upscale_factor < 1:
            raise ValueError("JANUS_OPENCV_UPSCALE_FACTOR must be at least 1")
        recognition_backend = os.getenv("JANUS_RECOGNITION_BACKEND", "mock")
        if recognition_backend not in {"mock", "tesseract"}:
            raise ValueError("JANUS_RECOGNITION_BACKEND must be mock or tesseract")
        return cls(
            environment=os.getenv("JANUS_ENV", "development"),
            api_key=os.getenv("JANUS_API_KEY", "janus-local-development-key"),
            recognition_backend=recognition_backend,
            opencv_upscale_factor=opencv_upscale_factor,
            max_file_size_bytes=max_file_size_bytes,
            processing_timeout_seconds=processing_timeout_seconds,
        )


settings = Settings.from_environment()
