"""
Circuit Breaker — prevents cascading failures.

States:
  CLOSED   → normal operation, requests pass through
  OPEN     → broker is failing, all calls fail fast (no network call)
  HALF_OPEN → after recovery timeout, one probe request is allowed

Transitions:
  CLOSED  → OPEN     : consecutive_failures >= threshold
  OPEN    → HALF_OPEN: recovery_timeout elapsed
  HALF_OPEN → CLOSED : probe succeeds (success_threshold met)
  HALF_OPEN → OPEN   : probe fails — reset timer
"""
from __future__ import annotations

import asyncio
import time
from enum import Enum
from typing import Callable, Awaitable, TypeVar

from app.core.config import get_settings
from app.core.logging import get_logger

settings = get_settings()
log = get_logger(__name__)

T = TypeVar("T")


class CircuitState(str, Enum):
    CLOSED    = "closed"
    OPEN      = "open"
    HALF_OPEN = "half_open"


class CircuitOpenError(Exception):
    def __init__(self, broker: str):
        super().__init__(f"Circuit breaker OPEN for broker '{broker}'. Refusing call.")
        self.broker = broker


class CircuitBreaker:
    def __init__(
        self,
        broker_name: str,
        failure_threshold: int   = None,
        recovery_timeout_s: int  = None,
        success_threshold: int   = None,
    ) -> None:
        self.broker_name       = broker_name
        self._failure_threshold = failure_threshold or settings.CB_FAILURE_THRESHOLD
        self._recovery_timeout  = recovery_timeout_s or settings.CB_RECOVERY_TIMEOUT_S
        self._success_threshold = success_threshold or settings.CB_SUCCESS_THRESHOLD

        self._state             = CircuitState.CLOSED
        self._failure_count     = 0
        self._success_count     = 0
        self._last_failure_time: float = 0.0
        self._lock              = asyncio.Lock()

    # ── Public API ────────────────────────────────────────────────────────────

    async def call(self, fn: Callable[..., Awaitable[T]], *args, **kwargs) -> T:
        """Execute fn, tracking success/failure for circuit state."""
        async with self._lock:
            await self._maybe_transition()
            if self._state == CircuitState.OPEN:
                raise CircuitOpenError(self.broker_name)

        try:
            result = await fn(*args, **kwargs)
            await self._on_success()
            return result
        except CircuitOpenError:
            raise
        except Exception as exc:
            await self._on_failure(exc)
            raise

    @property
    def state(self) -> CircuitState:
        return self._state

    @property
    def failure_count(self) -> int:
        return self._failure_count

    def to_dict(self) -> dict:
        return {
            "broker":          self.broker_name,
            "state":           self._state.value,
            "failure_count":   self._failure_count,
            "last_failure_at": self._last_failure_time or None,
        }

    # ── State machine ─────────────────────────────────────────────────────────

    async def _maybe_transition(self) -> None:
        if (
            self._state == CircuitState.OPEN
            and time.monotonic() - self._last_failure_time >= self._recovery_timeout
        ):
            self._state = CircuitState.HALF_OPEN
            self._success_count = 0
            log.warning("circuit_half_open", broker=self.broker_name)

    async def _on_success(self) -> None:
        async with self._lock:
            if self._state == CircuitState.HALF_OPEN:
                self._success_count += 1
                if self._success_count >= self._success_threshold:
                    self._state = CircuitState.CLOSED
                    self._failure_count = 0
                    log.info("circuit_closed", broker=self.broker_name)
            elif self._state == CircuitState.CLOSED:
                self._failure_count = 0

    async def _on_failure(self, exc: Exception) -> None:
        async with self._lock:
            self._failure_count += 1
            self._last_failure_time = time.monotonic()

            if self._state == CircuitState.HALF_OPEN:
                self._state = CircuitState.OPEN
                log.error("circuit_reopened", broker=self.broker_name, error=str(exc))
            elif (
                self._state == CircuitState.CLOSED
                and self._failure_count >= self._failure_threshold
            ):
                self._state = CircuitState.OPEN
                log.error(
                    "circuit_opened",
                    broker=self.broker_name,
                    failures=self._failure_count,
                    error=str(exc),
                )
