"""
Strategy Lifecycle Manager.

Each active strategy runs as a supervised asyncio.Task.
The manager handles:
  - Starting / stopping / pausing strategies
  - Injecting StrategyContext with latest bars from Redis
  - Sandboxed execution with timeout
  - Automatic restart with backoff on failure
  - State persistence between on_bar() calls
"""
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Optional

from app.core.config import get_settings
from app.core.logging import get_logger
from app.core.redis import get_redis
from app.publishers.signal import SignalPublisher
from app.registry.registry import StrategyRegistration, get_registry
from app.sandbox.executor import SandboxExecutor
from app.sdk.types import (
    BarData, Signal, StrategyContext, StrategyStatus, TradingMode,
)

settings = get_settings()
log = get_logger(__name__)


@dataclass
class StrategyInstance:
    """Runtime instance of a running strategy."""
    registration: StrategyRegistration
    strategy_obj: Any                    # StrategyBase instance
    symbol: str
    exchange: str
    timeframe: str
    trading_mode: TradingMode
    params: dict[str, Any]

    # Runtime state
    status: StrategyStatus = StrategyStatus.REGISTERED
    task: Optional[asyncio.Task] = None
    state: dict[str, Any] = field(default_factory=dict)
    restart_count: int = 0
    last_signal: Optional[Signal] = None
    last_bar_time: Optional[int] = None
    started_at: Optional[datetime] = None
    stopped_at: Optional[datetime] = None
    error: Optional[str] = None
    bars_processed: int = 0
    signals_emitted: int = 0

    @property
    def instance_id(self) -> str:
        return f"{self.registration.name}:{self.symbol}:{self.timeframe}"

    def to_dict(self) -> dict:
        return {
            "instance_id":     self.instance_id,
            "strategy_name":   self.registration.name,
            "version":         self.registration.version,
            "symbol":          self.symbol,
            "exchange":        self.exchange,
            "timeframe":       self.timeframe,
            "trading_mode":    self.trading_mode.value,
            "status":          self.status.value,
            "restart_count":   self.restart_count,
            "bars_processed":  self.bars_processed,
            "signals_emitted": self.signals_emitted,
            "started_at":      self.started_at.isoformat() if self.started_at else None,
            "stopped_at":      self.stopped_at.isoformat() if self.stopped_at else None,
            "error":           self.error,
            "last_bar_time":   self.last_bar_time,
            "params":          self.params,
        }


class StrategyLifecycleManager:
    """
    Manages all running strategy instances.

    Lifecycle per instance:
      register → start → [running] → pause | stop → [stopped]
                                   ↓ on error
                              restart (up to MAX_RESTARTS)
                                   ↓ exhausted
                              FAILED (manual intervention required)
    """

    def __init__(self) -> None:
        self._instances: dict[str, StrategyInstance] = {}
        self._lock = asyncio.Lock()
        self._sandbox = SandboxExecutor()
        self._publisher = SignalPublisher()

    # ── Public API ────────────────────────────────────────────────────────────

    async def start(
        self,
        strategy_name: str,
        symbol: str,
        exchange: str,
        timeframe: str,
        params: Optional[dict] = None,
        trading_mode: Optional[TradingMode] = None,
    ) -> StrategyInstance:
        registry = get_registry()
        reg = registry.get(strategy_name)
        if not reg:
            raise KeyError(f"Strategy '{strategy_name}' not in registry.")

        instance_id = f"{strategy_name}:{symbol}:{timeframe}"
        async with self._lock:
            if instance_id in self._instances:
                existing = self._instances[instance_id]
                if existing.status == StrategyStatus.RUNNING:
                    log.warning("strategy_already_running", instance_id=instance_id)
                    return existing

        effective_params = {**reg.metadata.parameters, **(params or {})}
        effective_mode = trading_mode or TradingMode(settings.TRADING_MODE)

        strategy_obj = reg.cls()
        instance = StrategyInstance(
            registration=reg,
            strategy_obj=strategy_obj,
            symbol=symbol,
            exchange=exchange,
            timeframe=timeframe,
            trading_mode=effective_mode,
            params=effective_params,
        )

        async with self._lock:
            self._instances[instance_id] = instance

        await self._launch(instance)
        return instance

    async def stop(self, instance_id: str) -> bool:
        async with self._lock:
            instance = self._instances.get(instance_id)
        if not instance:
            return False

        instance.status = StrategyStatus.STOPPED
        if instance.task and not instance.task.done():
            instance.task.cancel()
            try:
                await instance.task
            except asyncio.CancelledError:
                pass

        await instance.strategy_obj.on_stop()
        instance.stopped_at = datetime.now(UTC)
        log.info("strategy_stopped", instance_id=instance_id)
        return True

    async def pause(self, instance_id: str) -> bool:
        async with self._lock:
            instance = self._instances.get(instance_id)
        if not instance or instance.status != StrategyStatus.RUNNING:
            return False
        instance.status = StrategyStatus.PAUSED
        log.info("strategy_paused", instance_id=instance_id)
        return True

    async def resume(self, instance_id: str) -> bool:
        async with self._lock:
            instance = self._instances.get(instance_id)
        if not instance or instance.status != StrategyStatus.PAUSED:
            return False
        instance.status = StrategyStatus.RUNNING
        log.info("strategy_resumed", instance_id=instance_id)
        return True

    async def stop_all(self) -> None:
        ids = list(self._instances.keys())
        for iid in ids:
            await self.stop(iid)
        log.info("all_strategies_stopped", count=len(ids))

    def get_instance(self, instance_id: str) -> Optional[StrategyInstance]:
        return self._instances.get(instance_id)

    def list_instances(self) -> list[StrategyInstance]:
        return list(self._instances.values())

    # ── Internal ──────────────────────────────────────────────────────────────

    async def _launch(self, instance: StrategyInstance) -> None:
        instance.status = StrategyStatus.LOADING
        try:
            await instance.strategy_obj.on_start(instance.params)
        except Exception as exc:
            instance.status = StrategyStatus.FAILED
            instance.error = str(exc)
            log.error("strategy_on_start_failed",
                      instance_id=instance.instance_id, error=str(exc))
            return

        instance.status = StrategyStatus.RUNNING
        instance.started_at = datetime.now(UTC)
        instance.task = asyncio.create_task(
            self._run_loop(instance),
            name=f"strategy:{instance.instance_id}",
        )
        log.info("strategy_launched", instance_id=instance.instance_id,
                 mode=instance.trading_mode.value)

    async def _run_loop(self, instance: StrategyInstance) -> None:
        """
        Subscribe to Redis candle channel for this symbol/timeframe.
        On each new candle: build context → sandbox execute → publish signal.
        """
        import json
        channel = (
            f"{settings.REDIS_MARKET_CHANNEL_PREFIX}"
            f":candle:{instance.symbol}:{instance.timeframe}"
        )

        r = await get_redis()
        pubsub = r.pubsub()
        await pubsub.subscribe(channel)
        log.info("strategy_subscribed", instance_id=instance.instance_id, channel=channel)

        try:
            async for message in pubsub.listen():
                if instance.status == StrategyStatus.PAUSED:
                    await asyncio.sleep(0.1)
                    continue
                if instance.status != StrategyStatus.RUNNING:
                    break
                if message["type"] != "message":
                    continue

                try:
                    bar_data = json.loads(message["data"])
                    bar = _parse_bar(bar_data)
                    await self._process_bar(instance, bar)
                except asyncio.CancelledError:
                    break
                except Exception as exc:
                    log.error("strategy_bar_error",
                              instance_id=instance.instance_id, error=str(exc))
                    await self._handle_failure(instance, exc)
                    if instance.status == StrategyStatus.FAILED:
                        break

        except asyncio.CancelledError:
            pass
        finally:
            await pubsub.unsubscribe(channel)
            await pubsub.close()

    async def _process_bar(self, instance: StrategyInstance, bar: BarData) -> None:
        # Skip duplicate bars
        if instance.last_bar_time and bar.open_time <= instance.last_bar_time:
            return

        # Build context with recent bars from Redis
        bars = await _fetch_recent_bars(
            instance.symbol, instance.timeframe,
            n=max(instance.registration.metadata.min_bars_required + 10, 50),
        )

        ctx = StrategyContext(
            symbol=instance.symbol,
            exchange=instance.exchange,
            timeframe=instance.timeframe,
            trading_mode=instance.trading_mode,
            bars=bars,
            state=instance.state,
            params=instance.params,
        )

        # Sandboxed execution with timeout
        signal = await self._sandbox.execute(
            instance.strategy_obj.on_bar,
            ctx,
            timeout=settings.STRATEGY_EXECUTION_TIMEOUT_S,
        )

        instance.bars_processed += 1
        instance.last_bar_time = bar.open_time
        # Persist state mutations
        instance.state = ctx.state

        if signal is not None:
            signal.strategy_name = instance.registration.name
            signal.strategy_version = instance.registration.version
            signal.trading_mode = instance.trading_mode

            instance.last_signal = signal
            instance.signals_emitted += 1
            await self._publisher.publish(signal)

            log.info(
                "signal_emitted",
                instance_id=instance.instance_id,
                signal=signal.signal.value,
                confidence=signal.confidence,
                symbol=signal.symbol,
            )

    async def _handle_failure(self, instance: StrategyInstance, exc: Exception) -> None:
        instance.restart_count += 1
        instance.error = str(exc)

        if instance.restart_count > settings.STRATEGY_MAX_RESTARTS:
            instance.status = StrategyStatus.FAILED
            log.error("strategy_max_restarts_exceeded",
                      instance_id=instance.instance_id,
                      restarts=instance.restart_count)
            return

        log.warning("strategy_restarting",
                    instance_id=instance.instance_id,
                    restart=instance.restart_count,
                    backoff=settings.STRATEGY_RESTART_BACKOFF_S)

        instance.status = StrategyStatus.PAUSED
        await asyncio.sleep(settings.STRATEGY_RESTART_BACKOFF_S)
        instance.status = StrategyStatus.RUNNING


# ── Helpers ───────────────────────────────────────────────────────────────────

def _parse_bar(data: dict) -> BarData:
    return BarData(
        symbol=data["symbol"],
        exchange=data.get("exchange", "NSE"),
        timeframe=data["timeframe"],
        open_time=int(data["open_time"]),
        open=float(data["open"]),
        high=float(data["high"]),
        low=float(data["low"]),
        close=float(data["close"]),
        volume=int(data["volume"]),
        vwap=float(data.get("vwap", 0)),
        trade_count=int(data.get("trade_count", 0)),
    )


async def _fetch_recent_bars(symbol: str, timeframe: str, n: int) -> list[BarData]:
    """Fetch recent completed bars from Redis candle cache."""
    import json
    try:
        r = await get_redis()
        key = f"candle:{symbol}:{timeframe}"
        raw = await r.get(key)
        if raw:
            data = json.loads(raw)
            return [_parse_bar(data)]
    except Exception:
        pass
    return []


# ── Singleton ─────────────────────────────────────────────────────────────────

_manager: Optional[StrategyLifecycleManager] = None


def get_lifecycle_manager() -> StrategyLifecycleManager:
    global _manager
    if _manager is None:
        _manager = StrategyLifecycleManager()
    return _manager
