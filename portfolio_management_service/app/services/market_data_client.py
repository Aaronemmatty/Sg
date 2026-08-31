"""
Market Data Client for portfolio_management_service (8009).

Isolation guarantee: all market_data_service (8002) calls are isolated here.
If 8002 switches from REST to Redis-stream-only, only this file changes.

*** SAME ASSUMPTION AS 8008 (execution_engine_service) — CONFIRM BEFORE PROD ***
/symbols/{symbol}/ltp is assumed to return {"ltp": <float>}.
/symbols/{symbol}/history is assumed to return {"prices": [<float>, ...]} for
benchmark series (daily closes). If the endpoint differs, update _get_history.
"""
from __future__ import annotations

import httpx
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from app.core.config import settings
from app.core.logging import get_logger

log = get_logger(__name__)

_RETRY_EXCEPTIONS = (httpx.ConnectError, httpx.ConnectTimeout, httpx.ReadTimeout)


class MarketDataClient:
    def __init__(self) -> None:
        self._client = httpx.AsyncClient(
            base_url=settings.market_data_service_url,
            timeout=settings.market_data_timeout_seconds,
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    @retry(
        retry=retry_if_exception_type(_RETRY_EXCEPTIONS),
        stop=stop_after_attempt(2),
        wait=wait_exponential(multiplier=0.3, max=3),
        reraise=True,
    )
    async def get_last_price(self, symbol: str) -> float | None:
        """
        Fetch last-traded price for a symbol.
        Returns None on any failure (caller falls back to stale DB price).
        """
        try:
            resp = await self._client.get(f"/symbols/{symbol}/ltp")
            resp.raise_for_status()
            return float(resp.json()["ltp"])
        except Exception:
            log.warning("market_data_ltp_unavailable", symbol=symbol)
            return None

    @retry(
        retry=retry_if_exception_type(_RETRY_EXCEPTIONS),
        stop=stop_after_attempt(2),
        wait=wait_exponential(multiplier=0.3, max=3),
        reraise=True,
    )
    async def get_benchmark_series(
        self, symbol: str, days: int = 252
    ) -> list[float] | None:
        """
        Fetch historical daily close prices for benchmark comparison.
        Returns None if unavailable — benchmark metrics degrade gracefully.
        """
        try:
            resp = await self._client.get(
                f"/symbols/{symbol}/history",
                params={"days": days, "interval": "1d"},
            )
            resp.raise_for_status()
            data = resp.json()
            prices = data.get("prices") or [c["close"] for c in data.get("candles", [])]
            return [float(p) for p in prices]
        except Exception:
            log.warning("market_data_benchmark_series_unavailable", symbol=symbol)
            return None


market_data_client = MarketDataClient()
