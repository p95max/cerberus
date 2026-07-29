from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

from django.conf import settings

from domain.models import BarrierCommand, BarrierControlSettings


class BarrierControllerError(Exception):
    """Base error for the controller integration boundary."""


class BarrierControllerUnavailable(BarrierControllerError):
    pass


class BarrierControllerTimeout(BarrierControllerError):
    pass


@dataclass(frozen=True)
class BarrierControllerResult:
    acknowledged: bool


class BarrierController(ABC):
    @abstractmethod
    def open(self, command: BarrierCommand, *, timeout_seconds: int) -> BarrierControllerResult:
        """Send one open command to the physical or mock controller."""


class MockBarrierController(BarrierController):
    """Deterministic adapter used until a physical controller is integrated."""

    def open(self, command: BarrierCommand, *, timeout_seconds: int) -> BarrierControllerResult:
        if not settings.MOCK_BARRIER_AVAILABLE:
            raise BarrierControllerUnavailable("Mock barrier controller is unavailable.")
        if settings.MOCK_BARRIER_DELAY_SECONDS > timeout_seconds:
            raise BarrierControllerTimeout("Mock barrier controller timed out.")
        return BarrierControllerResult(acknowledged=True)


def get_barrier_controller() -> BarrierController:
    return MockBarrierController()


def barrier_control_defaults() -> dict[str, int]:
    return {"auto_close_seconds": settings.BARRIER_AUTO_CLOSE_SECONDS}


def barrier_auto_close_seconds() -> int:
    configured = BarrierControlSettings.objects.first()
    if configured is None:
        return settings.BARRIER_AUTO_CLOSE_SECONDS
    return configured.auto_close_seconds
