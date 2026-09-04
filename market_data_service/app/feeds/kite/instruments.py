"""
NSE Instrument Registry.

Downloads Kite's instrument dump (~1MB CSV) once per trading day,
caches in Redis, and provides symbol ↔ token lookups.
"""

from __future__ import annotations

import asyncio
import csv
import io
from typing import Optional

import httpx
from tenacity import AsyncRetrying, stop_after_attempt, wait_exponential

from app.core.config import get_settings
from app.core.logging import get_logger
from app.core.redis import get_redis
from app.core.types import Instrument

settings = get_settings()
log = get_logger(__name__)

INSTRUMENT_DUMP_URL = "https://api.kite.trade/instruments"
CACHE_KEY = "market:instruments:nse_eq"
CACHE_TTL = 86_400  # 24 hours — refresh daily


class InstrumentRegistry:
    """
    Loads the NSE EQ instrument dump from Kite and provides:
      - symbol → Instrument
      - token → Instrument
      - search by name prefix
    """

    def __init__(self) -> None:
        self._by_symbol: dict[str, Instrument] = {}
        self._by_token: dict[int, Instrument] = {}
        self._loaded = False

    async def load(self, force_refresh: bool = False) -> None:
        """Load instruments — from Redis cache or Kite API."""
        if self._loaded and not force_refresh:
            return

        # Try Redis cache first
        r = await get_redis()
        cached = await r.get(CACHE_KEY)
        if cached and not force_refresh:
            await self._parse_csv(cached)
            log.info("instruments_loaded_from_cache", count=len(self._by_symbol))
            return

        # Fetch from Kite
        csv_data = await self._fetch_from_kite()
        if csv_data:
            await r.setex(CACHE_KEY, CACHE_TTL, csv_data)
            await self._parse_csv(csv_data)
            log.info("instruments_loaded_from_kite", count=len(self._by_symbol))

        self._loaded = True

    async def _fetch_from_kite(self) -> Optional[str]:
        import redis.asyncio as redis_lib
        access_token = settings.KITE_ACCESS_TOKEN
        try:
            r_b2 = redis_lib.from_url("redis://127.0.0.1:6379/2")
            cached_token = await r_b2.get("sg:kite:access_token")
            if cached_token:
                access_token = cached_token.decode() if isinstance(cached_token, bytes) else str(cached_token)
            await r_b2.aclose()
        except Exception:
            pass
        headers = {
            "X-Kite-Version": "3",
            "Authorization": f"token {settings.KITE_API_KEY}:{access_token}",
        }
        async for attempt in AsyncRetrying(
            stop=stop_after_attempt(3),
            wait=wait_exponential(min=2, max=10),
        ):
            with attempt:
                async with httpx.AsyncClient(timeout=30.0) as client:
                    resp = await client.get(INSTRUMENT_DUMP_URL, headers=headers)
                    resp.raise_for_status()
                    return resp.text
        return None

    async def _parse_csv(self, csv_text: str) -> None:
        self._by_symbol.clear()
        self._by_token.clear()

        reader = csv.DictReader(io.StringIO(csv_text))
        for row in reader:
            try:
                # Only NSE equities
                if row.get("exchange") != "NSE":
                    continue
                if row.get("instrument_type") != "EQ":
                    continue

                inst = Instrument(
                    instrument_token=int(row["instrument_token"]),
                    exchange_token=int(row["exchange_token"]),
                    trading_symbol=row["tradingsymbol"],
                    name=row.get("name", ""),
                    exchange="NSE",
                    segment=row.get("segment", "NSE"),
                    instrument_type="EQ",
                    lot_size=int(row.get("lot_size", 1)),
                    tick_size=float(row.get("tick_size", 0.05)),
                )
                full_sym = f"NSE:{inst.trading_symbol}"
                self._by_symbol[full_sym] = inst
                self._by_symbol[inst.trading_symbol] = inst
                self._by_token[inst.instrument_token] = inst
            except (KeyError, ValueError):
                continue

    # ── Lookups ───────────────────────────────────────────────────────────────

    def get_by_symbol(self, symbol: str) -> Optional[Instrument]:
        return self._by_symbol.get(symbol) or self._by_symbol.get(f"NSE:{symbol}")

    def get_by_token(self, token: int) -> Optional[Instrument]:
        return self._by_token.get(token)

    def search(self, query: str, limit: int = 20) -> list[Instrument]:
        q = query.upper()
        results = [
            inst for sym, inst in self._by_symbol.items()
            if q in sym and ":" in sym   # only full symbol keys
        ]
        return results[:limit]

    def get_tokens(self, symbols: list[str]) -> dict[str, int]:
        result = {}
        for sym in symbols:
            inst = self.get_by_symbol(sym)
            if inst:
                result[f"NSE:{inst.trading_symbol}"] = inst.instrument_token
        return result

    @property
    def total_instruments(self) -> int:
        return len(self._by_token)


# Singleton — shared across the service
_registry: Optional[InstrumentRegistry] = None


def get_registry() -> InstrumentRegistry:
    global _registry
    if _registry is None:
        _registry = InstrumentRegistry()
    return _registry
