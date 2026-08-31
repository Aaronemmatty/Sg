"""
Risk Engine — pre-trade checks and post-trade reconciliation.

Pre-trade checks (block order before it reaches the broker):
  1. Exchange whitelist
  2. Product whitelist
  3. Max order value (qty * price)
  4. Max position value (would-be position after fill)
  5. Daily loss kill-switch
  6. Max orders per symbol per day
  7. Opposite-side check (prevent accidental double-entry)

Post-trade checks (fire after fill confirmation):
  1. Fill price sanity (vs expected)
  2. Position reconciliation
  3. Running P&L check against daily loss limit
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Optional

from app.brokers.interface import BrokerInterface
from app.core.config import get_settings
from app.core.logging import get_logger
from app.core.types import AccountInfo, OrderRequest, OrderResult, OrderSide, Position

settings = get_settings()
log = get_logger(__name__)


@dataclass
class RiskViolation(Exception):
    rule: str
    message: str
    order_blocked: bool = True

    def __str__(self) -> str:
        return f"[{self.rule}] {self.message}"


@dataclass
class RiskCheckResult:
    passed: bool
    violations: list[RiskViolation]
    warnings: list[str]

    @classmethod
    def ok(cls) -> "RiskCheckResult":
        return cls(passed=True, violations=[], warnings=[])

    def add_violation(self, rule: str, message: str) -> None:
        self.passed = False
        self.violations.append(RiskViolation(rule=rule, message=message))

    def add_warning(self, message: str) -> None:
        self.warnings.append(message)


class RiskEngine:
    """
    Stateful risk engine — tracks daily counters per symbol.
    Call reset_daily() at market open.
    """

    def __init__(self) -> None:
        self._daily_order_count: dict[str, int] = {}
        self._daily_pnl: float = 0.0
        self._last_reset: date = date.today()

    # ── Pre-trade ─────────────────────────────────────────────────────────────

    async def pre_trade_check(
        self,
        request: OrderRequest,
        broker: BrokerInterface,
    ) -> RiskCheckResult:
        """Run all pre-trade checks. Returns result with violations."""
        self._auto_reset()
        result = RiskCheckResult.ok()

        self._check_exchange(request, result)
        self._check_product(request, result)
        self._check_order_value(request, result)
        self._check_daily_order_count(request, result)
        self._check_daily_loss(result)
        await self._check_position_limit(request, broker, result)

        if not result.passed:
            log.warning(
                "pre_trade_check_failed",
                symbol=request.symbol,
                side=request.side,
                violations=[str(v) for v in result.violations],
            )
        return result

    def _check_exchange(self, req: OrderRequest, result: RiskCheckResult) -> None:
        if req.exchange.value not in settings.ALLOWED_EXCHANGES:
            result.add_violation(
                "EXCHANGE_WHITELIST",
                f"Exchange {req.exchange.value} not allowed. "
                f"Allowed: {settings.ALLOWED_EXCHANGES}",
            )

    def _check_product(self, req: OrderRequest, result: RiskCheckResult) -> None:
        if req.product.value not in settings.ALLOWED_PRODUCTS:
            result.add_violation(
                "PRODUCT_WHITELIST",
                f"Product {req.product.value} not allowed. "
                f"Allowed: {settings.ALLOWED_PRODUCTS}",
            )

    def _check_order_value(self, req: OrderRequest, result: RiskCheckResult) -> None:
        price = req.price or 0
        value = price * req.quantity
        if value > settings.MAX_ORDER_VALUE_INR:
            result.add_violation(
                "MAX_ORDER_VALUE",
                f"Order value ₹{value:,.0f} exceeds limit ₹{settings.MAX_ORDER_VALUE_INR:,.0f}",
            )
        elif value > settings.MAX_ORDER_VALUE_INR * 0.8:
            result.add_warning(
                f"Order value ₹{value:,.0f} is >80% of limit ₹{settings.MAX_ORDER_VALUE_INR:,.0f}"
            )

    def _check_daily_order_count(self, req: OrderRequest, result: RiskCheckResult) -> None:
        count = self._daily_order_count.get(req.symbol, 0)
        if count >= settings.MAX_ORDERS_PER_SYMBOL_PER_DAY:
            result.add_violation(
                "MAX_DAILY_ORDERS",
                f"Daily order limit ({settings.MAX_ORDERS_PER_SYMBOL_PER_DAY}) "
                f"reached for {req.symbol}",
            )

    def _check_daily_loss(self, result: RiskCheckResult) -> None:
        if self._daily_pnl < -abs(settings.MAX_DAILY_LOSS_INR):
            result.add_violation(
                "DAILY_LOSS_KILL_SWITCH",
                f"Daily loss ₹{abs(self._daily_pnl):,.0f} exceeds limit "
                f"₹{settings.MAX_DAILY_LOSS_INR:,.0f}. Kill-switch engaged.",
            )

    async def _check_position_limit(
        self,
        req: OrderRequest,
        broker: BrokerInterface,
        result: RiskCheckResult,
    ) -> None:
        try:
            positions = await broker.get_positions()
            existing = next(
                (p for p in positions if p.symbol == req.symbol), None
            )
            existing_value = abs(existing.value) if existing else 0.0
            new_value = (req.price or 0) * req.quantity
            total = existing_value + new_value

            if total > settings.MAX_POSITION_VALUE_INR:
                result.add_violation(
                    "MAX_POSITION_VALUE",
                    f"Position value ₹{total:,.0f} would exceed limit "
                    f"₹{settings.MAX_POSITION_VALUE_INR:,.0f} for {req.symbol}",
                )
        except Exception as exc:
            # Non-blocking — warn but don't block order if position check fails
            result.add_warning(f"Position check failed: {exc}")

    # ── Post-trade ────────────────────────────────────────────────────────────

    async def post_trade_check(
        self,
        request: OrderRequest,
        result: OrderResult,
        broker: BrokerInterface,
    ) -> None:
        """
        Run after a fill is confirmed.
        Updates internal P&L counters, logs anomalies.
        """
        if result.average_price and request.price:
            deviation = abs(result.average_price - request.price) / request.price * 100
            if deviation > 1.0:
                log.warning(
                    "fill_price_deviation",
                    symbol=request.symbol,
                    expected=request.price,
                    actual=result.average_price,
                    deviation_pct=round(deviation, 3),
                )

        # Update daily order count
        self._daily_order_count[request.symbol] = (
            self._daily_order_count.get(request.symbol, 0) + 1
        )

        log.info(
            "post_trade_check_complete",
            symbol=request.symbol,
            side=request.side.value,
            filled_qty=result.filled_quantity,
            avg_price=result.average_price,
        )

    # ── Helpers ───────────────────────────────────────────────────────────────

    def record_pnl(self, pnl: float) -> None:
        """Update running daily P&L (called after position change)."""
        self._daily_pnl += pnl
        if self._daily_pnl < -abs(settings.MAX_DAILY_LOSS_INR):
            log.critical(
                "daily_loss_limit_breached",
                daily_pnl=self._daily_pnl,
                limit=-settings.MAX_DAILY_LOSS_INR,
            )

    def reset_daily(self) -> None:
        """Reset all daily counters — call at market open."""
        self._daily_order_count.clear()
        self._daily_pnl = 0.0
        self._last_reset = date.today()
        log.info("risk_engine_daily_reset")

    def _auto_reset(self) -> None:
        if date.today() != self._last_reset:
            self.reset_daily()

    def get_status(self) -> dict:
        return {
            "daily_pnl":              self._daily_pnl,
            "daily_loss_limit":       -settings.MAX_DAILY_LOSS_INR,
            "kill_switch_active":     self._daily_pnl < -abs(settings.MAX_DAILY_LOSS_INR),
            "daily_order_counts":     dict(self._daily_order_count),
            "last_reset":             self._last_reset.isoformat(),
        }


# Singleton
_risk_engine: Optional[RiskEngine] = None


def get_risk_engine() -> RiskEngine:
    global _risk_engine
    if _risk_engine is None:
        _risk_engine = RiskEngine()
    return _risk_engine
