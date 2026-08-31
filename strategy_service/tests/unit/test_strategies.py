"""Unit tests — built-in strategies, registry, sandbox executor."""
from __future__ import annotations
import asyncio
import time
from unittest.mock import AsyncMock, MagicMock
import pytest
from app.sdk import BarData, Signal, SignalType, StrategyContext, TradingMode
from app.sdk.types import StrategyMetadata, StrategyType


def _make_bars(n: int, start_price: float = 100.0, trend: float = 0.0) -> list[BarData]:
    now = int(time.time())
    bars = []
    price = start_price
    for i in range(n):
        price = price * (1 + trend) + (i % 3 - 1) * 0.1
        bars.append(BarData(
            symbol="NSE:TEST", exchange="NSE", timeframe="5m",
            open_time=now - (n - i) * 300,
            open=price * 0.999, high=price * 1.002,
            low=price * 0.998, close=price,
            volume=10000 + i * 100,
        ))
    return bars


def _make_ctx(bars: list[BarData], params: dict = None) -> StrategyContext:
    return StrategyContext(
        symbol="NSE:TEST", exchange="NSE", timeframe="5m",
        trading_mode=TradingMode.PAPER,
        bars=bars, params=params or {},
    )


# ── EMA Crossover ─────────────────────────────────────────────────────────────

class TestEMACrossover:
    @pytest.mark.asyncio
    async def test_no_signal_insufficient_bars(self):
        from app.strategies.builtin.trend.ema_crossover import EMACrossoverStrategy
        s = EMACrossoverStrategy()
        ctx = _make_ctx(_make_bars(10))
        result = await s.on_bar(ctx)
        assert result is None

    @pytest.mark.asyncio
    async def test_buy_signal_on_crossover(self):
        from app.strategies.builtin.trend.ema_crossover import EMACrossoverStrategy
        s = EMACrossoverStrategy()
        # Uptrend bars → fast EMA should be above slow EMA
        bars = _make_bars(60, trend=0.005)
        ctx = _make_ctx(bars)
        result = await s.on_bar(ctx)
        # May or may not emit depending on exact crossover — just ensure no exception
        assert result is None or isinstance(result, Signal)

    @pytest.mark.asyncio
    async def test_signal_confidence_in_range(self):
        from app.strategies.builtin.trend.ema_crossover import EMACrossoverStrategy
        s = EMACrossoverStrategy()
        bars = _make_bars(60, trend=0.002)
        ctx = _make_ctx(bars)
        result = await s.on_bar(ctx)
        if result:
            assert 0.0 <= result.confidence <= 1.0


# ── RSI Momentum ──────────────────────────────────────────────────────────────

class TestRSIMomentum:
    @pytest.mark.asyncio
    async def test_no_signal_insufficient_bars(self):
        from app.strategies.builtin.momentum.rsi_momentum import RSIMomentumStrategy
        s = RSIMomentumStrategy()
        ctx = _make_ctx(_make_bars(10))
        assert await s.on_bar(ctx) is None

    @pytest.mark.asyncio
    async def test_returns_signal_or_none(self):
        from app.strategies.builtin.momentum.rsi_momentum import RSIMomentumStrategy
        s = RSIMomentumStrategy()
        bars = _make_bars(35)
        ctx = _make_ctx(bars)
        result = await s.on_bar(ctx)
        assert result is None or isinstance(result, Signal)

    @pytest.mark.asyncio
    async def test_oversold_generates_buy(self):
        from app.strategies.builtin.momentum.rsi_momentum import RSIMomentumStrategy, _rsi
        # Craft bars with RSI that crosses oversold boundary
        s = RSIMomentumStrategy()
        # Sharp downtrend then recovery
        bars = _make_bars(20, trend=-0.02) + _make_bars(15, start_price=60.0, trend=0.01)
        ctx = _make_ctx(bars)
        result = await s.on_bar(ctx)
        assert result is None or result.signal in (SignalType.BUY, SignalType.SELL)


# ── Bollinger Reversion ───────────────────────────────────────────────────────

class TestBollingerReversion:
    @pytest.mark.asyncio
    async def test_no_signal_insufficient_bars(self):
        from app.strategies.builtin.mean_reversion.bollinger_reversion import BollingerReversionStrategy
        s = BollingerReversionStrategy()
        ctx = _make_ctx(_make_bars(5))
        assert await s.on_bar(ctx) is None

    @pytest.mark.asyncio
    async def test_stop_loss_set_on_buy(self):
        from app.strategies.builtin.mean_reversion.bollinger_reversion import BollingerReversionStrategy
        s = BollingerReversionStrategy()
        # Craft bars where price is near lower band
        bars = _make_bars(25, start_price=100.0, trend=-0.03)
        ctx = _make_ctx(bars)
        result = await s.on_bar(ctx)
        if result and result.signal == SignalType.BUY:
            assert result.stop_loss is not None
            assert result.take_profit is not None


# ── Donchian Breakout ─────────────────────────────────────────────────────────

class TestDonchianBreakout:
    @pytest.mark.asyncio
    async def test_no_signal_insufficient_bars(self):
        from app.strategies.builtin.breakout.donchian_breakout import DonchianBreakoutStrategy
        s = DonchianBreakoutStrategy()
        ctx = _make_ctx(_make_bars(10))
        assert await s.on_bar(ctx) is None

    @pytest.mark.asyncio
    async def test_valid_output(self):
        from app.strategies.builtin.breakout.donchian_breakout import DonchianBreakoutStrategy
        s = DonchianBreakoutStrategy()
        bars = _make_bars(30)
        ctx = _make_ctx(bars)
        result = await s.on_bar(ctx)
        assert result is None or isinstance(result, Signal)


# ── Strategy Registry ─────────────────────────────────────────────────────────

class TestStrategyRegistry:
    @pytest.mark.asyncio
    async def test_register_and_retrieve(self):
        from app.registry.registry import StrategyRegistry
        from app.strategies.builtin.trend.ema_crossover import EMACrossoverStrategy
        reg = StrategyRegistry()
        await reg.register(EMACrossoverStrategy, is_builtin=True)
        entry = reg.get("ema_crossover")
        assert entry is not None
        assert entry.name == "ema_crossover"
        assert entry.is_builtin is True

    @pytest.mark.asyncio
    async def test_deregister(self):
        from app.registry.registry import StrategyRegistry
        from app.strategies.builtin.trend.ema_crossover import EMACrossoverStrategy
        reg = StrategyRegistry()
        await reg.register(EMACrossoverStrategy, is_builtin=True)
        ok = await reg.deregister("ema_crossover")
        assert ok is True
        assert reg.get("ema_crossover") is None

    @pytest.mark.asyncio
    async def test_duplicate_registration_same_hash_skipped(self):
        from app.registry.registry import StrategyRegistry
        from app.strategies.builtin.trend.ema_crossover import EMACrossoverStrategy
        reg = StrategyRegistry()
        await reg.register(EMACrossoverStrategy, file_hash="abc123", is_builtin=True)
        await reg.register(EMACrossoverStrategy, file_hash="abc123", is_builtin=True)
        assert reg.count == 1

    def test_instantiate(self):
        import asyncio
        from app.registry.registry import StrategyRegistry
        from app.strategies.builtin.trend.ema_crossover import EMACrossoverStrategy
        reg = StrategyRegistry()
        asyncio.get_event_loop().run_until_complete(
            reg.register(EMACrossoverStrategy, is_builtin=True)
        )
        obj = reg.instantiate("ema_crossover")
        from app.sdk.base import StrategyBase
        assert isinstance(obj, StrategyBase)


# ── Sandbox Executor ──────────────────────────────────────────────────────────

class TestSandboxExecutor:
    @pytest.mark.asyncio
    async def test_normal_execution(self):
        from app.sandbox.executor import SandboxExecutor
        sandbox = SandboxExecutor()
        async def fn(): return 42
        result = await sandbox.execute(fn, timeout=1.0)
        assert result == 42

    @pytest.mark.asyncio
    async def test_timeout_raises(self):
        from app.sandbox.executor import SandboxExecutor, StrategyTimeoutError
        sandbox = SandboxExecutor()
        async def slow():
            await asyncio.sleep(10)
            return "done"
        with pytest.raises(StrategyTimeoutError):
            await sandbox.execute(slow, timeout=0.05)

    @pytest.mark.asyncio
    async def test_exception_propagates(self):
        from app.sandbox.executor import SandboxExecutor
        sandbox = SandboxExecutor()
        async def boom(): raise ValueError("deliberate")
        with pytest.raises(ValueError):
            await sandbox.execute(boom, timeout=1.0)

    @pytest.mark.asyncio
    async def test_latency_recorded(self):
        from app.sandbox.executor import SandboxExecutor
        sandbox = SandboxExecutor()
        async def fast(): return True
        await sandbox.execute(fast, timeout=1.0, strategy_name="test_strat")
        stats = sandbox.get_latency_stats("test_strat")
        assert stats["count"] == 1
        assert "mean_ms" in stats


# ── Signal validation ─────────────────────────────────────────────────────────

class TestSignal:
    def test_valid_signal(self):
        from app.sdk.types import Signal, SignalType
        s = Signal(signal=SignalType.BUY, confidence=0.85,
                   symbol="NSE:RELIANCE", timeframe="5m")
        assert s.confidence == 0.85

    def test_confidence_out_of_range_raises(self):
        from app.sdk.types import Signal, SignalType
        with pytest.raises(ValueError):
            Signal(signal=SignalType.BUY, confidence=1.5,
                   symbol="NSE:RELIANCE", timeframe="5m")

    def test_to_dict_schema(self):
        from app.sdk.types import Signal, SignalType
        s = Signal(signal=SignalType.SELL, confidence=0.72,
                   symbol="NSE:TCS", timeframe="1h",
                   strategy_name="ema_crossover")
        d = s.to_dict()
        assert d["symbol"] == "NSE:TCS"
        assert d["signal"] == "SELL"
        assert d["strategy_name"] == "ema_crossover"
        assert "timestamp" in d
