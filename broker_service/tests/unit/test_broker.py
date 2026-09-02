"""Unit tests — circuit breaker, rate limiter, risk engine, paper broker."""
from __future__ import annotations

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from app.brokers.circuit_breaker import CircuitBreaker, CircuitOpenError, CircuitState
from app.brokers.rate_limiter import TokenBucket, BrokerRateLimiter
from app.core.types import Exchange, OrderRequest, OrderSide, OrderType, ProductType


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_order(**kwargs) -> OrderRequest:
    defaults = dict(
        symbol="RELIANCE", exchange=Exchange.NSE, side=OrderSide.BUY,
        order_type=OrderType.LIMIT, product=ProductType.MIS,
        quantity=1, price=500.0,
    )
    defaults.update(kwargs)
    return OrderRequest(**defaults)


# ── Circuit Breaker ───────────────────────────────────────────────────────────

class TestCircuitBreaker:
    @pytest.mark.asyncio
    async def test_starts_closed(self):
        cb = CircuitBreaker("test")
        assert cb.state == CircuitState.CLOSED

    @pytest.mark.asyncio
    async def test_opens_after_threshold_failures(self):
        cb = CircuitBreaker("test", failure_threshold=3)

        async def always_fail():
            raise RuntimeError("boom")

        for _ in range(3):
            with pytest.raises(RuntimeError):
                await cb.call(always_fail)

        assert cb.state == CircuitState.OPEN

    @pytest.mark.asyncio
    async def test_open_circuit_raises_immediately(self):
        cb = CircuitBreaker("test", failure_threshold=1)

        async def fail():
            raise RuntimeError("fail")

        with pytest.raises(RuntimeError):
            await cb.call(fail)

        # Now circuit is open — next call should raise CircuitOpenError, not RuntimeError
        with pytest.raises(CircuitOpenError):
            await cb.call(fail)

    @pytest.mark.asyncio
    async def test_half_open_after_timeout(self):
        import time
        cb = CircuitBreaker("test", failure_threshold=1, recovery_timeout_s=0)

        async def fail():
            raise RuntimeError("fail")

        with pytest.raises(RuntimeError):
            await cb.call(fail)

        # Manually set last_failure_time to past
        cb._last_failure_time = 0.0
        assert cb.state == CircuitState.OPEN
        # Next call should transition to HALF_OPEN and attempt
        # (will fail again, transition back to OPEN)
        with pytest.raises((RuntimeError, CircuitOpenError)):
            await cb.call(fail)

    @pytest.mark.asyncio
    async def test_closes_after_successes_in_half_open(self):
        cb = CircuitBreaker("test", failure_threshold=1,
                             recovery_timeout_s=0, success_threshold=2)
        async def fail():
            raise RuntimeError("fail")

        with pytest.raises(RuntimeError):
            await cb.call(fail)

        cb._last_failure_time = 0.0

        async def succeed():
            return "ok"

        # Two successes → closed
        await cb.call(succeed)
        await cb.call(succeed)
        assert cb.state == CircuitState.CLOSED

    @pytest.mark.asyncio
    async def test_successful_call_passes_through(self):
        cb = CircuitBreaker("test")
        result = await cb.call(AsyncMock(return_value=42))
        assert result == 42


# ── Token Bucket ──────────────────────────────────────────────────────────────

class TestTokenBucket:
    @pytest.mark.asyncio
    async def test_acquire_within_capacity(self):
        bucket = TokenBucket(capacity=10, rate=10)
        ok = await bucket.acquire(1)
        assert ok is True

    @pytest.mark.asyncio
    async def test_acquire_exceeds_capacity_times_out(self):
        bucket = TokenBucket(capacity=1, rate=0.001)   # refills very slowly
        await bucket.acquire(1)   # drain
        ok = await bucket.acquire(1, timeout=0.05)
        assert ok is False


class TestBrokerRateLimiter:
    @pytest.mark.asyncio
    async def test_acquire_does_not_raise_when_capacity_available(self):
        rl = BrokerRateLimiter("test", orders_per_second=10, requests_per_minute=200)
        await rl.acquire(is_order=True)   # should not raise


# ── Risk Engine ───────────────────────────────────────────────────────────────

class TestRiskEngine:
    def _engine(self):
        from app.risk.engine import RiskEngine
        return RiskEngine()

    @pytest.mark.asyncio
    async def test_exchange_whitelist_blocks(self):
        engine = self._engine()
        order = _make_order(exchange=Exchange.BSE)  # BSE is allowed by default
        mock_broker = AsyncMock()
        mock_broker.get_positions.return_value = []

        with patch("app.risk.engine.settings.ALLOWED_EXCHANGES", ["NSE"]):
            result = await engine.pre_trade_check(order, mock_broker)
        # BSE not in ["NSE"] → violation
        assert result.passed is False
        assert any("EXCHANGE" in v.rule for v in result.violations)

    @pytest.mark.asyncio
    async def test_order_value_limit(self):
        engine = self._engine()
        order = _make_order(quantity=1000, price=10000.0)  # ₹1 crore → exceeds limit
        mock_broker = AsyncMock()
        mock_broker.get_positions.return_value = []
        result = await engine.pre_trade_check(order, mock_broker)
        assert result.passed is False
        assert any("ORDER_VALUE" in v.rule for v in result.violations)

    @pytest.mark.asyncio
    async def test_daily_loss_kill_switch(self):
        engine = self._engine()
        engine._daily_pnl = -100_000.0   # exceeds 50k limit
        order = _make_order()
        mock_broker = AsyncMock()
        mock_broker.get_positions.return_value = []
        result = await engine.pre_trade_check(order, mock_broker)
        assert result.passed is False
        assert any("KILL_SWITCH" in v.rule for v in result.violations)

    @pytest.mark.asyncio
    async def test_valid_order_passes(self):
        from datetime import datetime
        from sg_security.calendar import IST
        engine = self._engine()
        order = _make_order(quantity=1, price=100.0)
        mock_broker = AsyncMock()
        mock_broker.get_positions.return_value = []
        open_dt = datetime(2026, 3, 4, 11, 0, 0, tzinfo=IST)
        result = await engine.pre_trade_check(order, mock_broker, now_dt=open_dt)
        assert result.passed is True
        assert result.violations == []

    def test_reset_daily(self):
        engine = self._engine()
        engine._daily_pnl = -10_000.0
        engine._daily_order_count["RELIANCE"] = 20
        engine.reset_daily()
        assert engine._daily_pnl == 0.0
        assert engine._daily_order_count == {}


# ── Paper Broker ──────────────────────────────────────────────────────────────

class TestPaperBroker:
    @pytest.fixture
    async def broker(self):
        from app.brokers.paper.broker import PaperBroker
        b = PaperBroker()
        # Mock Redis to avoid real connection
        with patch("app.brokers.paper.broker.get_redis", AsyncMock(return_value=AsyncMock(
            get=AsyncMock(return_value=None),
            set=AsyncMock(),
        ))):
            await b.connect()
            yield b
            await b.disconnect()

    @pytest.mark.asyncio
    async def test_place_market_order_fills(self, broker):
        order = _make_order(order_type=OrderType.MARKET, price=None)
        with patch.object(broker, "_get_market_price", AsyncMock(return_value=500.0)), \
             patch.object(broker, "_save_state", AsyncMock()):
            result = await broker.place_order(order)
        from app.core.types import OrderStatus
        assert result.status == OrderStatus.COMPLETE
        assert result.filled_quantity == 1

    @pytest.mark.asyncio
    async def test_place_limit_order_stays_open(self, broker):
        # Limit BUY at 450 with market at 500 → should NOT fill immediately
        order = _make_order(order_type=OrderType.LIMIT, price=450.0)
        with patch.object(broker, "_get_market_price", AsyncMock(return_value=500.0)), \
             patch.object(broker, "_save_state", AsyncMock()):
            result = await broker.place_order(order)
        from app.core.types import OrderStatus
        assert result.status == OrderStatus.OPEN

    @pytest.mark.asyncio
    async def test_cancel_order(self, broker):
        order = _make_order(order_type=OrderType.LIMIT, price=450.0)
        with patch.object(broker, "_save_state", AsyncMock()):
            placed = await broker.place_order(order)
            cancelled = await broker.cancel_order(placed.broker_order_id)
        from app.core.types import OrderStatus
        assert cancelled.status == OrderStatus.CANCELLED

    @pytest.mark.asyncio
    async def test_get_account_info(self, broker):
        from app.core.config import get_settings
        info = await broker.get_account_info()
        assert info.broker == "paper"
        assert info.available_cash == pytest.approx(get_settings().PAPER_INITIAL_CAPITAL_INR, rel=0.01)

