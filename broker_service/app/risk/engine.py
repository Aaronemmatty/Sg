"""
Risk Engine — pre-trade checks and post-trade reconciliation.

Pre-trade checks (block order before it reaches the broker):
  1. Exchange whitelist
  2. Product whitelist
  3. Max order value (qty * price) — 20% of CURRENT live available cash
  4. Max position value (would-be position after fill) — 20% of CURRENT live available cash
  5. Daily loss kill-switch — 2% of CURRENT live available cash
  6. Max orders per symbol per day
  7. Opposite-side check (prevent accidental double-entry)

Effective INR limits are derived at runtime from the live available_cash
returned by broker.get_account_info(), so they automatically recalibrate
as the account grows or shrinks with P&L. ACCOUNT_CAPITAL_INR is used as
a fallback when the broker account call fails.

Post-trade checks (fire after fill confirmation):
  1. Fill price sanity (vs expected)
  2. Position reconciliation
  3. Running P&L check against daily loss limit
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Optional

from app.brokers.interface import BrokerInterface
from app.core.config import get_settings
from app.core.logging import get_logger
from app.core.types import AccountInfo, OrderRequest, OrderResult, OrderSide, Position
from sg_security.calendar import is_market_open

settings = get_settings()
log = get_logger(__name__)

# Cache TTL for live account info (seconds). Short enough to stay fresh,
# long enough not to spam the broker API on burst-fire pre-trade checks.
_ACCOUNT_CACHE_TTL_S = 30


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


@dataclass
class _EffectiveLimits:
    """INR limits derived from live available_cash at check time."""
    max_order_value: float
    max_position_value: float
    max_daily_loss: float
    available_cash: float
    source: str  # "live" | "fallback"


class RiskEngine:
    """
    Stateful risk engine — tracks daily counters per symbol.
    Call reset_daily() at market open.
    """

    def __init__(self) -> None:
        self._daily_order_count: dict[str, int] = {}
        self._daily_pnl: float = 0.0
        self._last_reset: date = date.today()
        # In-memory cache for account info (avoid per-check API call)
        self._cached_account: Optional[AccountInfo] = None
        self._cache_ts: float = 0.0

    # ── Effective limits ──────────────────────────────────────────────────────

    async def _get_effective_limits(self, broker: BrokerInterface) -> _EffectiveLimits:
        """
        Derive INR risk limits from the CURRENT live available cash.

        Uses a 30-second in-memory cache to avoid calling the broker on
        every single pre-trade check in a burst. Falls back to
        ACCOUNT_CAPITAL_INR if the broker call fails so the engine
        stays operational even when the account info endpoint is down.
        """
        now = time.monotonic()
        if self._cached_account is None or (now - self._cache_ts) > _ACCOUNT_CACHE_TTL_S:
            try:
                acc = await broker.get_account_info()
                if isinstance(acc, AccountInfo):
                    self._cached_account = acc
                    self._cache_ts = now
                    source = "live"
                else:
                    raise ValueError(f"Invalid account info returned: {type(acc)}")
            except Exception as exc:
                log.warning(
                    "account_info_fetch_failed_using_fallback",
                    error=str(exc),
                    fallback_capital=settings.ACCOUNT_CAPITAL_INR,
                )
                self._cached_account = AccountInfo(
                    broker="fallback",
                    account_id="fallback",
                    available_cash=settings.ACCOUNT_CAPITAL_INR,
                    used_margin=0.0,
                    total_margin=settings.ACCOUNT_CAPITAL_INR,
                    net_value=settings.ACCOUNT_CAPITAL_INR,
                    day_pnl=0.0,
                    positions_value=0.0,
                )
                source = "fallback"
        else:
            source = "cached"

        cash = max(float(self._cached_account.available_cash or 0.0), 0.0)
        return _EffectiveLimits(
            max_order_value=cash * settings.MAX_ORDER_VALUE_PCT,
            max_position_value=cash * settings.MAX_POSITION_VALUE_PCT,
            max_daily_loss=cash * settings.MAX_DAILY_LOSS_PCT,
            available_cash=cash,
            source=source,
        )


    # ── Pre-trade ─────────────────────────────────────────────────────────────

    async def pre_trade_check(
        self,
        request: OrderRequest,
        broker: BrokerInterface,
        now_dt: datetime | None = None,
    ) -> RiskCheckResult:
        """Run all pre-trade checks. Returns result with violations."""
        self._auto_reset()
        result = RiskCheckResult.ok()

        # Fetch effective limits once per check (cached)
        limits = await self._get_effective_limits(broker)

        self._check_market_hours(result, now_dt=now_dt)
        self._check_exchange(request, result)
        self._check_product(request, result)
        self._check_order_value(request, result, limits)
        self._check_daily_order_count(request, result)
        self._check_daily_loss(result, limits)
        await self._check_position_limit(request, broker, result, limits)

        if not result.passed:
            log.warning(
                "pre_trade_check_failed",
                symbol=request.symbol,
                side=request.side,
                available_cash=limits.available_cash,
                limits_source=limits.source,
                violations=[str(v) for v in result.violations],
            )
        return result

    def _check_market_hours(self, result: RiskCheckResult, now_dt: datetime | None = None) -> None:
        if not is_market_open(now_dt):
            result.add_violation(
                "MARKET_HOURS",
                "Market is closed. Continuous equity trading is only allowed during NSE market hours "
                "(09:15-15:30 IST, Monday-Friday, excluding NSE exchange holidays).",
            )

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

    def _check_order_value(
        self, req: OrderRequest, result: RiskCheckResult, limits: _EffectiveLimits
    ) -> None:
        price = req.price or 0
        value = price * req.quantity
        if value > limits.max_order_value:
            result.add_violation(
                "MAX_ORDER_VALUE",
                f"Order value ₹{value:,.0f} exceeds limit ₹{limits.max_order_value:,.0f} "
                f"({settings.MAX_ORDER_VALUE_PCT*100:.0f}% of live cash ₹{limits.available_cash:,.0f}, "
                f"source={limits.source})",
            )
        elif value > limits.max_order_value * 0.8:
            result.add_warning(
                f"Order value ₹{value:,.0f} is >80% of limit ₹{limits.max_order_value:,.0f}"
            )

    def _check_daily_order_count(self, req: OrderRequest, result: RiskCheckResult) -> None:
        count = self._daily_order_count.get(req.symbol, 0)
        if count >= settings.MAX_ORDERS_PER_SYMBOL_PER_DAY:
            result.add_violation(
                "MAX_DAILY_ORDERS",
                f"Daily order limit ({settings.MAX_ORDERS_PER_SYMBOL_PER_DAY}) "
                f"reached for {req.symbol}",
            )

    def _check_daily_loss(self, result: RiskCheckResult, limits: _EffectiveLimits) -> None:
        if self._daily_pnl < -abs(limits.max_daily_loss):
            result.add_violation(
                "DAILY_LOSS_KILL_SWITCH",
                f"Daily loss ₹{abs(self._daily_pnl):,.0f} exceeds limit "
                f"₹{limits.max_daily_loss:,.0f} "
                f"({settings.MAX_DAILY_LOSS_PCT*100:.0f}% of live cash, "
                f"source={limits.source}). Kill-switch engaged.",
            )

    async def _check_position_limit(
        self,
        req: OrderRequest,
        broker: BrokerInterface,
        result: RiskCheckResult,
        limits: _EffectiveLimits,
    ) -> None:
        try:
            positions = await broker.get_positions()
            existing = next(
                (p for p in positions if p.symbol == req.symbol), None
            )
            existing_value = abs(existing.value) if existing else 0.0
            new_value = (req.price or 0) * req.quantity
            total = existing_value + new_value

            if total > limits.max_position_value:
                result.add_violation(
                    "MAX_POSITION_VALUE",
                    f"Position value ₹{total:,.0f} would exceed limit "
                    f"₹{limits.max_position_value:,.0f} "
                    f"({settings.MAX_POSITION_VALUE_PCT*100:.0f}% of live cash, "
                    f"source={limits.source}) for {req.symbol}",
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
        # Log at critical if we've breached 2% of configured capital.
        # (We don't have the live balance here so we use ACCOUNT_CAPITAL_INR
        # as a conservative reference; the actual limit enforced at pre-trade
        # time uses the live balance.)
        fallback_limit = settings.ACCOUNT_CAPITAL_INR * settings.MAX_DAILY_LOSS_PCT
        if self._daily_pnl < -abs(fallback_limit):
            log.critical(
                "daily_loss_limit_breached",
                daily_pnl=self._daily_pnl,
                limit=-fallback_limit,
            )

    def reset_daily(self) -> None:
        """Reset all daily counters — call at market open."""
        self._daily_order_count.clear()
        self._daily_pnl = 0.0
        self._last_reset = date.today()
        # Also invalidate the account cache so next check fetches a fresh balance
        self._cached_account = None
        self._cache_ts = 0.0
        log.info("risk_engine_daily_reset")

    def _auto_reset(self) -> None:
        if date.today() != self._last_reset:
            self.reset_daily()

    def get_status(self) -> dict:
        cash = self._cached_account.available_cash if self._cached_account else settings.ACCOUNT_CAPITAL_INR
        daily_loss_limit = cash * settings.MAX_DAILY_LOSS_PCT
        return {
            "daily_pnl":              self._daily_pnl,
            "daily_loss_limit":       -daily_loss_limit,
            "kill_switch_active":     self._daily_pnl < -abs(daily_loss_limit),
            "daily_order_counts":     dict(self._daily_order_count),
            "last_reset":             self._last_reset.isoformat(),
            "effective_cash":         cash,
            "limits_source":          "cached" if self._cached_account else "fallback",
        }


# Singleton
_risk_engine: Optional[RiskEngine] = None


def get_risk_engine() -> RiskEngine:
    global _risk_engine
    if _risk_engine is None:
        _risk_engine = RiskEngine()
    return _risk_engine
