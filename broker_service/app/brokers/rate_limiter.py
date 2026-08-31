"""
Token Bucket Rate Limiter — async, per-broker.

Two buckets per broker:
  1. per-second  (orders_per_second)   — for order placement
  2. per-minute  (requests_per_minute) — for all API calls

Kite limits:
  - Orders: 10/sec
  - API calls: 200/min (3.33/sec)
"""
from __future__ import annotations

import asyncio
import time

from app.core.config import get_settings
from app.core.logging import get_logger

settings = get_settings()
log = get_logger(__name__)


class TokenBucket:
    """
    Leaky token bucket.
    Tokens refill at `rate` per second up to `capacity`.
    """

    def __init__(self, capacity: float, rate: float) -> None:
        self._capacity  = capacity
        self._rate      = rate        # tokens per second
        self._tokens    = capacity
        self._last_refill = time.monotonic()
        self._lock      = asyncio.Lock()

    async def acquire(self, tokens: float = 1.0, timeout: float = 5.0) -> bool:
        """
        Wait until `tokens` tokens are available, up to `timeout` seconds.
        Returns True if acquired, False if timed out.
        """
        deadline = time.monotonic() + timeout
        while True:
            async with self._lock:
                self._refill()
                if self._tokens >= tokens:
                    self._tokens -= tokens
                    return True

            wait = (tokens - self._tokens) / self._rate
            if time.monotonic() + wait > deadline:
                return False
            await asyncio.sleep(min(wait, 0.05))

    def _refill(self) -> None:
        now = time.monotonic()
        elapsed = now - self._last_refill
        self._tokens = min(self._capacity, self._tokens + elapsed * self._rate)
        self._last_refill = now

    @property
    def available(self) -> float:
        return self._tokens


class BrokerRateLimiter:
    """Composite rate limiter: per-second + per-minute buckets."""

    def __init__(
        self,
        broker_name: str,
        orders_per_second: float = None,
        requests_per_minute: int = None,
    ) -> None:
        self.broker_name = broker_name
        ops = orders_per_second or settings.KITE_ORDERS_PER_SECOND
        rpm = requests_per_minute or settings.KITE_REQUESTS_PER_MINUTE

        # Per-second bucket: capacity = rate (burst = 1 second worth)
        self._second_bucket = TokenBucket(capacity=ops, rate=ops)
        # Per-minute bucket: capacity = rpm, refill at rpm/60 per second
        self._minute_bucket = TokenBucket(capacity=float(rpm), rate=rpm / 60.0)

    async def acquire(self, is_order: bool = False) -> None:
        """
        Acquire rate limit tokens. Raises RuntimeError if timed out.
        is_order=True also checks the per-second order bucket.
        """
        # Always check per-minute
        ok_min = await self._minute_bucket.acquire(timeout=5.0)
        if not ok_min:
            log.warning("rate_limit_minute_exceeded", broker=self.broker_name)
            raise RuntimeError(f"Rate limit exceeded (per-minute) for {self.broker_name}")

        # For order placement: also check per-second
        if is_order:
            ok_sec = await self._second_bucket.acquire(timeout=2.0)
            if not ok_sec:
                log.warning("rate_limit_second_exceeded", broker=self.broker_name)
                raise RuntimeError(f"Rate limit exceeded (per-second) for {self.broker_name}")

    def status(self) -> dict:
        return {
            "broker":             self.broker_name,
            "second_tokens":      round(self._second_bucket.available, 2),
            "minute_tokens":      round(self._minute_bucket.available, 2),
        }
