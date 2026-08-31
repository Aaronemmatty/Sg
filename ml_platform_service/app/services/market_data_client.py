"""
Market Data Client — fetches OHLCV history from market_data_service (8002).

Isolation guarantee: if 8002 changes its API shape, only this file changes.
Assumption: GET /symbols/{symbol}/candles?limit=N&interval=1d returns
  {"candles": [{"timestamp":..., "open":..., "high":..., "low":..., "close":..., "volume":...}]}
Same unconfirmed assumption as in 8008/8009.
"""
from __future__ import annotations

import pandas as pd
import httpx
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from app.core.config import settings
from app.core.logging import get_logger

log = get_logger(__name__)
_RETRY_EXC = (httpx.ConnectError, httpx.ConnectTimeout, httpx.ReadTimeout)


class MarketDataClient:
    def __init__(self) -> None:
        self._client = httpx.AsyncClient(
            base_url=settings.market_data_service_url,
            timeout=settings.market_data_timeout_seconds,
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    @retry(retry=retry_if_exception_type(_RETRY_EXC), stop=stop_after_attempt(2),
           wait=wait_exponential(multiplier=0.3, max=3), reraise=True)
    async def get_ohlcv(self, symbol: str, bars: int = 500, interval: str = "1d") -> pd.DataFrame | None:
        """Fetch OHLCV history as a pandas DataFrame. Returns None on failure."""
        try:
            resp = await self._client.get(
                f"/symbols/{symbol}/candles",
                params={"limit": bars, "interval": interval},
            )
            resp.raise_for_status()
            candles = resp.json().get("candles", [])
            if not candles:
                return None
            df = pd.DataFrame(candles)
            df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
            df = df.set_index("timestamp").sort_index()
            for col in ["open", "high", "low", "close", "volume"]:
                df[col] = df[col].astype(float)
            return df
        except Exception:
            log.warning("ohlcv_fetch_failed", symbol=symbol)
            return None

    @retry(retry=retry_if_exception_type(_RETRY_EXC), stop=stop_after_attempt(2),
           wait=wait_exponential(multiplier=0.3, max=3), reraise=True)
    async def get_last_price(self, symbol: str) -> float | None:
        try:
            resp = await self._client.get(f"/symbols/{symbol}/ltp")
            resp.raise_for_status()
            return float(resp.json()["ltp"])
        except Exception:
            return None


market_data_client = MarketDataClient()
