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

import json
import redis.asyncio as aioredis
import httpx
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from app.config import settings
from app.logging_config import get_logger

log = get_logger(__name__)

# Approximate base prices for fallback when live feed is cold
FALLBACK_PRICES = {
    "NSE:RELIANCE": 2960.0,
    "RELIANCE": 2960.0,
    "NSE:TCS": 3800.0,
    "TCS": 3800.0,
    "NSE:INFY": 1750.0,
    "INFY": 1750.0,
    "NSE:HDFC": 1680.0,
    "HDFC": 1680.0,
    "NSE:ICICIBANK": 1150.0,
    "ICICIBANK": 1150.0,
    "NSE:SBIN": 825.0,
    "SBIN": 825.0,
}


class MarketDataClient:
    def __init__(self, base_url: str | None = None) -> None:
        self._base_url = base_url or getattr(settings, "market_data_service_url", "http://localhost:8002")
        self._client = httpx.AsyncClient(base_url=self._base_url, timeout=3.0)
        self._redis: aioredis.Redis | None = None

    async def aclose(self) -> None:
        if self._redis:
            await self._redis.close()
        await self._client.aclose()

    async def _get_redis(self) -> aioredis.Redis:
        if self._redis is None:
            self._redis = aioredis.from_url(settings.redis_url, decode_responses=True)
        return self._redis

    async def get_last_price(self, symbol: str) -> float | None:
        # 1. Try Redis tick cache
        try:
            r = await self._get_redis()
            for key in [f"tick:{symbol}", f"tick:NSE:{symbol}", f"tick:{symbol.replace('NSE:', '')}"]:
                raw = await r.get(key)
                if raw:
                    data = json.loads(raw)
                    ltp = data.get("last_price") or data.get("ltp") or data.get("price")
                    if ltp:
                        return float(ltp)
        except Exception:
            pass

        # 2. Try REST API on market_data_service
        try:
            resp = await self._client.get(f"/v1/market/quote/{symbol}")
            if resp.status_code == 200:
                data = resp.json()
                return float(data.get("last_price") or data.get("ltp") or data.get("price"))
        except Exception:
            pass

        # 3. Fallback to default prices
        if symbol in FALLBACK_PRICES:
            log.info("using_fallback_market_price", symbol=symbol, price=FALLBACK_PRICES[symbol])
            return FALLBACK_PRICES[symbol]

        return 1000.0


market_data_client = MarketDataClient()
