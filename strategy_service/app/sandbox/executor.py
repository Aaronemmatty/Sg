"""
Sandbox Executor — isolates each strategy on_bar() call.

Responsibilities:
  - Enforce execution timeout (STRATEGY_EXECUTION_TIMEOUT_S)
  - Catch all exceptions — a crashing strategy must never crash the framework
  - Measure latency per call for performance tracking
"""
from __future__ import annotations

import asyncio
import time
from typing import Any, Awaitable, Callable, Optional, TypeVar

from app.core.logging import get_logger

log = get_logger(__name__)
T = TypeVar("T")


class StrategyTimeoutError(Exception):
    pass


class SandboxExecutor:
    def __init__(self) -> None:
        self._call_times: dict[str, list[float]] = {}

    async def execute(
        self,
        fn: Callable[..., Awaitable[Optional[T]]],
        *args,
        timeout: float = 5.0,
        strategy_name: str = "",
        **kwargs,
    ) -> Optional[T]:
        """
        Execute fn(*args, **kwargs) with timeout.
        Returns result or None on timeout / exception.
        """
        start = time.perf_counter()
        try:
            result = await asyncio.wait_for(fn(*args, **kwargs), timeout=timeout)
            elapsed = time.perf_counter() - start
            self._record_latency(strategy_name, elapsed)
            return result

        except asyncio.TimeoutError:
            elapsed = time.perf_counter() - start
            log.warning(
                "strategy_timeout",
                strategy=strategy_name,
                timeout_s=timeout,
                elapsed_ms=round(elapsed * 1000, 1),
            )
            raise StrategyTimeoutError(
                f"Strategy '{strategy_name}' exceeded {timeout}s timeout."
            )

        except StrategyTimeoutError:
            raise

        except Exception as exc:
            elapsed = time.perf_counter() - start
            log.error(
                "strategy_execution_error",
                strategy=strategy_name,
                error=str(exc),
                elapsed_ms=round(elapsed * 1000, 1),
                exc_info=True,
            )
            # Re-raise so lifecycle manager can handle restart logic
            raise

    def _record_latency(self, name: str, elapsed: float) -> None:
        if not name:
            return
        history = self._call_times.setdefault(name, [])
        history.append(elapsed * 1000)   # store in ms
        if len(history) > 1000:
            history.pop(0)

    def get_latency_stats(self, name: str) -> dict:
        history = self._call_times.get(name, [])
        if not history:
            return {}
        import statistics
        return {
            "count":   len(history),
            "mean_ms": round(statistics.mean(history), 2),
            "p50_ms":  round(statistics.median(history), 2),
            "p99_ms":  round(sorted(history)[int(len(history) * 0.99)], 2),
            "max_ms":  round(max(history), 2),
        }
