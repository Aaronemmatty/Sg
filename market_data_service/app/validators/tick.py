"""Data quality validator — rejects bad ticks before they enter the system."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from app.core.config import get_settings
from app.core.logging import get_logger
from app.core.types import Tick

settings = get_settings()
log = get_logger(__name__)


@dataclass
class ValidationResult:
    valid: bool
    reason: Optional[str] = None

    @classmethod
    def ok(cls) -> "ValidationResult":
        return cls(valid=True)

    @classmethod
    def fail(cls, reason: str) -> "ValidationResult":
        return cls(valid=False, reason=reason)


class TickValidator:
    """
    Stateful validator — tracks last price per symbol to detect spikes.
    All checks are O(1) dict lookups. Thread-safe via asyncio single-thread model.
    """

    def __init__(self) -> None:
        self._last_price: dict[str, float] = {}
        self._rejected_count: dict[str, int] = {}

    def validate(self, tick: Tick) -> ValidationResult:
        # 1. Price floor
        if tick.last_price < settings.MIN_VALID_PRICE:
            return self._reject(tick, f"price {tick.last_price} below minimum {settings.MIN_VALID_PRICE}")

        # 2. Negative volume
        if tick.volume < 0:
            return self._reject(tick, f"negative volume {tick.volume}")

        # 3. Price spike vs last known price
        last = self._last_price.get(tick.symbol)
        if last and last > 0:
            deviation = abs(tick.last_price - last) / last * 100
            if deviation > settings.MAX_PRICE_DEVIATION_PCT:
                return self._reject(
                    tick,
                    f"price spike {deviation:.1f}% (last={last}, new={tick.last_price})",
                )

        # 4. NaN / Inf guard
        if not _is_finite(tick.last_price):
            return self._reject(tick, "non-finite price")

        # All checks passed — update last price
        self._last_price[tick.symbol] = tick.last_price
        return ValidationResult.ok()

    def _reject(self, tick: Tick, reason: str) -> ValidationResult:
        self._rejected_count[tick.symbol] = self._rejected_count.get(tick.symbol, 0) + 1
        log.warning(
            "tick_rejected",
            symbol=tick.symbol,
            reason=reason,
            total_rejected=self._rejected_count[tick.symbol],
        )
        return ValidationResult.fail(reason)

    def reset_symbol(self, symbol: str) -> None:
        """Call at market open to clear stale last-price state."""
        self._last_price.pop(symbol, None)

    def reset_all(self) -> None:
        self._last_price.clear()
        self._rejected_count.clear()

    @property
    def rejection_counts(self) -> dict[str, int]:
        return dict(self._rejected_count)


def _is_finite(value: float) -> bool:
    import math
    return math.isfinite(value)
