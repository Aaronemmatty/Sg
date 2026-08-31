"""Base feed interface and mock feed for offline development."""

from __future__ import annotations

import asyncio
import math
import random
import time
from abc import ABC, abstractmethod
from typing import Callable, Awaitable

from app.core.logging import get_logger
from app.core.types import Tick

log = get_logger(__name__)


class BaseFeed(ABC):
    def __init__(self, on_tick: Callable[[Tick], Awaitable[None]]) -> None:
        self.on_tick = on_tick

    @abstractmethod
    async def start(self) -> None: ...

    @abstractmethod
    async def stop(self) -> None: ...

    @abstractmethod
    async def subscribe(self, symbol_token_map: dict[str, int]) -> None: ...


class MockFeed(BaseFeed):
    """
    Synthetic tick generator — simulates realistic NSE price action.

    Uses geometric Brownian motion for price simulation:
      dS = μS dt + σS dW
    where dW ~ N(0, dt).

    Useful for:
      - Local dev without Kite API key
      - Integration tests
      - Strategy development
    """

    # Realistic NSE symbols for simulation
    DEFAULT_SYMBOLS: dict[str, int] = {
        "NSE:RELIANCE":  738561,
        "NSE:TCS":       2953217,
        "NSE:INFY":      408065,
        "NSE:HDFC":      341249,
        "NSE:ICICIBANK": 1270529,
        "NSE:SBIN":      779521,
        "NSE:WIPRO":     969473,
        "NSE:AXISBANK":  1510401,
        "NSE:BAJFINANCE":4267265,
        "NSE:KOTAKBANK": 492033,
    }

    # Approximate base prices (as of 2025)
    BASE_PRICES: dict[str, float] = {
        "NSE:RELIANCE":  2950.0,
        "NSE:TCS":       3800.0,
        "NSE:INFY":      1750.0,
        "NSE:HDFC":      1680.0,
        "NSE:ICICIBANK": 1150.0,
        "NSE:SBIN":       825.0,
        "NSE:WIPRO":      480.0,
        "NSE:AXISBANK":  1095.0,
        "NSE:BAJFINANCE":6800.0,
        "NSE:KOTAKBANK": 1780.0,
    }

    def __init__(
        self,
        on_tick: Callable[[Tick], Awaitable[None]],
        tick_interval_ms: float = 500,   # ticks per 500ms per symbol
        drift: float = 0.0,              # annual drift μ
        volatility: float = 0.20,        # annual volatility σ
    ) -> None:
        super().__init__(on_tick)
        self._tick_interval = tick_interval_ms / 1000.0
        self._drift = drift
        self._volatility = volatility
        self._prices: dict[str, float] = {}
        self._volumes: dict[str, int] = {}
        self._symbols: dict[str, int] = {}
        self._running = False
        self._task: asyncio.Task | None = None

    async def start(self) -> None:
        self._running = True
        self._task = asyncio.create_task(self._generate(), name="mock-feed")
        log.info("mock_feed_started", tick_interval_ms=self._tick_interval * 1000)

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
        log.info("mock_feed_stopped")

    async def subscribe(self, symbol_token_map: dict[str, int]) -> None:
        for symbol, token in symbol_token_map.items():
            self._symbols[symbol] = token
            if symbol not in self._prices:
                self._prices[symbol] = self.BASE_PRICES.get(symbol, 1000.0)
                self._volumes[symbol] = 0
        log.info("mock_feed_subscribed", count=len(self._symbols))

    async def _generate(self) -> None:
        dt = self._tick_interval / (252 * 6.25 * 3600)   # fraction of trading year
        sqrt_dt = math.sqrt(dt)

        while self._running:
            now_ns = time.time_ns()
            for symbol in list(self._symbols.keys()):
                price = self._prices[symbol]

                # GBM step
                z = random.gauss(0, 1)
                new_price = price * math.exp(
                    (self._drift - 0.5 * self._volatility ** 2) * dt
                    + self._volatility * sqrt_dt * z
                )
                # Clamp to realistic range (±5% per tick max)
                new_price = max(price * 0.95, min(price * 1.05, new_price))
                new_price = round(new_price, 2)

                # Simulate volume (log-normal intraday pattern)
                tick_vol = max(1, int(random.lognormvariate(4, 1)))
                self._volumes[symbol] += tick_vol
                self._prices[symbol] = new_price

                tick = Tick(
                    instrument_token=self._symbols[symbol],
                    symbol=symbol,
                    exchange="NSE",
                    last_price=new_price,
                    volume=self._volumes[symbol],
                    timestamp_ns=now_ns,
                    open=self.BASE_PRICES.get(symbol, price),
                    high=new_price * 1.002,
                    low=new_price * 0.998,
                    close=price,
                )

                try:
                    await self.on_tick(tick)
                except Exception as exc:
                    log.error("mock_tick_error", symbol=symbol, error=str(exc))

            await asyncio.sleep(self._tick_interval)
