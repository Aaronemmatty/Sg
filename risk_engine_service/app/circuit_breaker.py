from __future__ import annotations

from typing import Any

from app.logging_setup import get_logger
from app.metrics import CIRCUIT_BREAKER_TRIPPED
from app.redis_bus import RedisBus
from app.repository import Database

log = get_logger(module="circuit_breaker")

CB_KEY_PREFIX = "sg:risk:circuit_breaker:"


class CircuitBreakerRegistry:
    """Symbol-level trading halt, distinct from the global kill switch.
    Tripped when a symbol's intraday move exceeds the configured
    threshold within the configured window. Auto-resets after a cool-down
    once the move check is back under the threshold AND the explicit
    reset window has elapsed (tracked via Redis TTL)."""

    def __init__(self, redis_bus: RedisBus, db: Database) -> None:
        self._redis = redis_bus
        self._db = db

    async def is_tripped(self, symbol: str) -> bool:
        val = await self._redis.get_hot_key(f"{CB_KEY_PREFIX}{symbol}")
        return val is not None and val.get("tripped", False)

    async def trip(self, symbol: str, reason: str, metric_value: float | None, threshold: float | None, cool_down_seconds: int = 300) -> None:
        await self._redis.set_hot_key(
            f"{CB_KEY_PREFIX}{symbol}",
            {"tripped": True, "reason": reason},
            ttl_seconds=cool_down_seconds,
        )
        CIRCUIT_BREAKER_TRIPPED.labels(symbol=symbol).set(1)
        await self._db.insert_circuit_breaker_event(symbol, "TRIPPED", reason, metric_value, threshold)
        log.error("circuit_breaker_tripped", symbol=symbol, reason=reason, metric_value=metric_value, threshold=threshold)

    async def reset(self, symbol: str, reason: str = "manual_reset") -> None:
        assert self._redis.client is not None
        await self._redis.client.delete(f"{CB_KEY_PREFIX}{symbol}")
        CIRCUIT_BREAKER_TRIPPED.labels(symbol=symbol).set(0)
        await self._db.insert_circuit_breaker_event(symbol, "RESET", reason, None, None)
        log.info("circuit_breaker_reset", symbol=symbol)

    async def status_all(self, symbols: list[str]) -> dict[str, Any]:
        out = {}
        for s in symbols:
            out[s] = await self.is_tripped(s)
        return out
