"""
Minimal client for market_data_service (8002) — execution_engine only needs
last-traded-price for order sizing (quantity = allocation / price) and as the
"intended price" reference for slippage calculation.

*** CONFIRM BEFORE GOING LIVE ***
/symbols/{symbol}/ltp is NOT a confirmed endpoint on 8002 (the risk_engine
team flagged the same uncertainty for /symbols/{symbol}/volatility and
/correlation-matrix). If 8002 exposes price differently (e.g. via the
existing Redis candle stream sg:market:candle:{symbol}:{tf} instead of REST),
swap the implementation of `get_last_price` only — callers are unaffected.
"""
from __future__ import annotations

import httpx
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from app.config import settings
from app.logging_config import get_logger

log = get_logger(__name__)

_MARKET_DATA_BASE_URL = "http://market_data_service:8002"  # override via env if needed in deployment


class MarketDataClient:
    def __init__(self, base_url: str = _MARKET_DATA_BASE_URL) -> None:
        self._client = httpx.AsyncClient(base_url=base_url, timeout=3.0)

    async def aclose(self) -> None:
        await self._client.aclose()

    @retry(
        retry=retry_if_exception_type((httpx.ConnectError, httpx.ConnectTimeout, httpx.ReadTimeout)),
        stop=stop_after_attempt(2),
        wait=wait_exponential(multiplier=0.3, max=3),
        reraise=True,
    )
    async def get_last_price(self, symbol: str) -> float | None:
        try:
            resp = await self._client.get(f"/symbols/{symbol}/ltp")
            resp.raise_for_status()
            data = resp.json()
            return float(data["ltp"])
        except Exception:
            log.warning("market_data_ltp_unavailable", symbol=symbol)
            return None


market_data_client = MarketDataClient()
