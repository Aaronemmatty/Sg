"""Redis cache + pub/sub wrapper, following the platform's key/channel conventions."""
from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator
from datetime import datetime

import redis.asyncio as aioredis

from app.config import Settings
from app.models.domain import RegimeResult

logger = logging.getLogger(__name__)


def _json_default(o):
    if isinstance(o, datetime):
        return o.isoformat()
    return str(o)


class RegimeRedisClient:
    def __init__(self, settings: Settings):
        self.settings = settings
        self._redis: aioredis.Redis | None = None

    async def connect(self) -> None:
        self._redis = aioredis.from_url(self.settings.REDIS_URL, decode_responses=True)
        await self._redis.ping()
        logger.info("connected to redis at %s", self.settings.REDIS_URL)

    async def close(self) -> None:
        if self._redis is not None:
            await self._redis.aclose()

    @property
    def client(self) -> aioredis.Redis:
        if self._redis is None:
            raise RuntimeError("RegimeRedisClient.connect() must be called before use")
        return self._redis

    def _regime_key(self, symbol: str, timeframe: str) -> str:
        return f"{self.settings.REDIS_KEY_PREFIX_REGIME}:{symbol}:{timeframe}"

    def _regime_channel(self, symbol: str) -> str:
        return f"{self.settings.REDIS_CHANNEL_REGIME_PREFIX}:{symbol}"

    def _candle_channel(self, symbol: str, timeframe: str) -> str:
        return f"{self.settings.REDIS_CHANNEL_CANDLE_PREFIX}:{symbol}:{timeframe}"

    # --- Regime cache -----------------------------------------------------------

    async def get_cached_regime(self, symbol: str, timeframe: str) -> RegimeResult | None:
        raw = await self.client.get(self._regime_key(symbol, timeframe))
        if raw is None:
            return None
        try:
            return RegimeResult.model_validate_json(raw)
        except Exception:  # noqa: BLE001
            logger.exception("failed to deserialize cached regime for %s:%s", symbol, timeframe)
            return None

    async def set_cached_regime(self, result: RegimeResult, ttl_seconds: int = 900) -> None:
        key = self._regime_key(result.symbol, result.timeframe)
        await self.client.set(key, result.model_dump_json(), ex=ttl_seconds)

    # --- Pub/sub ------------------------------------------------------------------

    async def publish_regime_event(self, result: RegimeResult, event_type: str) -> None:
        channel = self._regime_channel(result.symbol)
        payload = {
            "event_type": event_type,
            "symbol": result.symbol,
            "timeframe": result.timeframe,
            "regime": result.regime.value,
            "confidence": result.confidence,
            "sub_regimes": [r.value for r in result.sub_regimes],
            "timestamp": result.timestamp.isoformat(),
        }
        await self.client.publish(channel, json.dumps(payload, default=_json_default))

    async def subscribe_candles(self, symbols_timeframes: list[tuple[str, str]]) -> aioredis.client.PubSub:
        pubsub = self.client.pubsub()
        channels = [self._candle_channel(s, tf) for s, tf in symbols_timeframes]
        await pubsub.subscribe(*channels)
        logger.info("subscribed to candle channels: %s", channels)
        return pubsub

    async def listen(self, pubsub: aioredis.client.PubSub) -> AsyncIterator[dict]:
        async for message in pubsub.listen():
            if message.get("type") != "message":
                continue
            try:
                yield json.loads(message["data"])
            except (TypeError, json.JSONDecodeError):
                logger.warning("dropped malformed pub/sub message on %s", message.get("channel"))
                continue

    # --- Misc cached inputs -----------------------------------------------------

    async def get_latest_tick(self, exchange: str, symbol: str) -> dict | None:
        raw = await self.client.get(f"tick:{exchange}:{symbol}")
        return json.loads(raw) if raw else None

    async def get_latest_candle(self, symbol: str, timeframe: str) -> dict | None:
        raw = await self.client.get(f"candle:{symbol}:{timeframe}")
        return json.loads(raw) if raw else None

    async def set_regime_lookup(self, symbol: str, timeframe: str, regime: str) -> None:
        """Lightweight key other services can read without parsing the full JSON blob."""
        await self.client.set(f"regime:{symbol}:{timeframe}:label", regime, ex=900)
