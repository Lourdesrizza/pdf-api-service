from collections.abc import Iterator
from contextlib import contextmanager
from enum import Enum, auto
from math import ceil
from time import monotonic

from app.clients.base import UpstreamFailure
from app.errors import APIError


FAILURE_THRESHOLD = 3
COOLDOWN_SECONDS = 10


class CircuitState(Enum):
    CLOSED = auto()
    OPEN = auto()
    HALF_OPEN = auto()


class CircuitBreaker:
    """Track operation outcomes within a single client and event loop."""

    def __init__(self, service: str):
        self._service = service
        self._state = CircuitState.CLOSED
        self._failures = 0
        self._retry_at = 0.0
        self._generation = 0

    @contextmanager
    def operation(self) -> Iterator[bool]:
        """Admit an operation and tell the caller whether it is the recovery probe."""
        # Admission and accounting have no awaits, so one task claims the probe.
        now = monotonic()
        if self._state is CircuitState.HALF_OPEN or (
            self._state is CircuitState.OPEN and now < self._retry_at
        ):
            raise APIError(
                503,
                "upstream_unavailable",
                f"El servicio {self._service} no está disponible.",
                headers={"Retry-After": str(max(1, ceil(self._retry_at - now)))},
            )

        probe = self._state is CircuitState.OPEN
        if probe:
            self._state = CircuitState.HALF_OPEN
        generation = self._generation
        failed = None
        try:
            yield probe
        except APIError as exc:
            failed = isinstance(exc, UpstreamFailure)
            raise
        else:
            failed = False
        finally:
            # Ignore calls admitted before an opening. A cancelled probe has
            # no outcome and reopens the circuit so a future probe can run.
            if generation == self._generation:
                self._record(failed, probe)

    def _record(self, failed: bool | None, probe: bool) -> None:
        if failed is False:
            self._state = CircuitState.CLOSED
            self._failures = 0
            return
        if failed:
            self._failures += 1
        if probe or self._failures >= FAILURE_THRESHOLD:
            self._state = CircuitState.OPEN
            self._retry_at = monotonic() + COOLDOWN_SECONDS
            self._generation += 1
