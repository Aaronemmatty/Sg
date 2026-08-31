"""Redis interface — tick cache, candle state, pub/sub channels."""

from __future__ import annotations

import json
from typing import Any

import redis.asyncio as aioredis

from app.core.config import get_settings
from app.core.logging import get_logger

settings = get_settings()
log = get_logger(__name__)

_pool: aioredis.Redis | None = None

CH_TICK   = f"{settings.REDIS_CHANNEL_PREFIX}:tick"
CH_CANDLE = f"{settings.REDIS_CHANNEL_PREFIX}:candle"
CH_STATUS = f"{settings.REDIS_CHANNEL_PREFIX}:status"


async def get_redis() -> aioredis.Redis:
    global _pool
    if _pool is None:
        _pool = await aioredis.from_url(
            str(settings.REDIS_URL),
            encoding="utf-8",
            decode_responses=True,
            max_connections=30,
        )
    return _pool


async def close_redis() -> None:
    global _pool
    if _pool:
        await _pool.aclose()
        _pool = None


# ── Tick cache ────────────────────────────────────────────────────────────────

def _tick_key(symbol: str) -> str:
    return f"tick:{symbol}"


async def cache_tick(symbol: str, data: dict[str, Any]) -> None:
    r = await get_redis()
    await r.setex(_tick_key(symbol), settings.REDIS_TICK_TTL, json.dumps(data))


async def get_cached_tick(symbol: str) -> dict[str, Any] | None:
    r = await get_redis()
    raw = await r.get(_tick_key(symbol))
    return json.loads(raw) if raw else None


async def get_all_ticks(symbols: list[str]) -> dict[str, Any]:
    r = await get_redis()
    keys = [_tick_key(s) for s in symbols]
    values = await r.mget(*keys)
    result = {}
    for sym, val in zip(symbols, values):
        if val:
            result[sym] = json.loads(val)
    return result


# ── Live candle state (in-progress candle per symbol per timeframe) ───────────

def _candle_key(symbol: str, timeframe_label: str) -> str:
    return f"candle:{symbol}:{timeframe_label}"


async def store_candle(symbol: str, timeframe_label: str, data: dict[str, Any]) -> None:
    r = await get_redis()
    # TTL = timeframe duration + 60s buffer
    ttl = settings.REDIS_CANDLE_TTL
    await r.setex(_candle_key(symbol, timeframe_label), ttl, json.dumps(data))


async def get_candle(symbol: str, timeframe_label: str) -> dict[str, Any] | None:
    r = await get_redis()
    raw = await r.get(_candle_key(symbol, timeframe_label))
    return json.loads(raw) if raw else None


async def delete_candle(symbol: str, timeframe_label: str) -> None:
    r = await get_redis()
    await r.delete(_candle_key(symbol, timeframe_label))


# ── Last volume tracker (for delta volume computation) ────────────────────────

async def get_last_volume(symbol: str) -> int:
    r = await get_redis()
    val = await r.get(f"last_vol:{symbol}")
    return int(val) if val else 0


async def set_last_volume(symbol: str, volume: int) -> None:
    r = await get_redis()
    await r.setex(f"last_vol:{symbol}", settings.REDIS_TICK_TTL, volume)


# ── Pub/Sub publishing ────────────────────────────────────────────────────────

async def publish_tick(data: dict[str, Any]) -> None:
    r = await get_redis()
    channel = f"{CH_TICK}:{data['symbol']}"
    await r.publish(channel, json.dumps(data))


async def publish_candle(data: dict[str, Any]) -> None:
    r = await get_redis()
    channel = f"{CH_CANDLE}:{data['symbol']}:{data['timeframe']}"
    await r.publish(channel, json.dumps(data))


async def publish_status(data: dict[str, Any]) -> None:
    r = await get_redis()
    await r.publish(CH_STATUS, json.dumps(data))


# ── Subscription registry (which symbols are being watched) ──────────────────

SUBSCRIPTIONS_KEY = "market:subscriptions"


async def add_subscription(symbol: str, instrument_token: int) -> None:
    r = await get_redis()
    await r.hset(SUBSCRIPTIONS_KEY, symbol, instrument_token)


async def remove_subscription(symbol: str) -> None:
    r = await get_redis()
    await r.hdel(SUBSCRIPTIONS_KEY, symbol)


async def get_subscriptions() -> dict[str, int]:
    r = await get_redis()
    raw = await r.hgetall(SUBSCRIPTIONS_KEY)
    return {k: int(v) for k, v in raw.items()}


async def clear_subscriptions() -> None:
    r = await get_redis()
    await r.delete(SUBSCRIPTIONS_KEY)


# ── Feed health ───────────────────────────────────────────────────────────────

async def set_feed_status(status: str, details: dict | None = None) -> None:
    r = await get_redis()
    payload = {"status": status, **(details or {})}
    await r.set("market:feed:status", json.dumps(payload), ex=120)


async def get_feed_status() -> dict[str, Any]:
    r = await get_redis()
    raw = await r.get("market:feed:status")
    return json.loads(raw) if raw else {"status": "unknown"}
