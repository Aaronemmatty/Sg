"""
Redis cache + pub/sub wrapper for signal_aggregation_service.

Collects strategy signals two ways:
  1. Known registry (`settings.STRATEGY_REGISTRY`) — direct key GETs, fast path.
  2. SCAN over `signal:*:{symbol}:{timeframe}` — catches any strategy (including genuinely
     custom ones) that isn't in the static registry, so "Custom Strategies" from the brief
     are supported without a code change.
Results are deduplicated by strategy name (registry + SCAN may overlap).
"""
from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator
from datetime import datetime

import redis.asyncio as aioredis

from app.config import Settings
from app.models.domain import AggregatedSignalResult, RegimeRef

logger = logging.getLogger(__name__)


def _json_default(o):
    if isinstance(o, datetime):
        return o.isoformat()
    return str(o)


class AggregationRedisClient:
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
            raise RuntimeError("AggregationRedisClient.connect() must be called before use")
        return self._redis

    # --- Strategy signal collection ------------------------------------------------

    async def get_raw_signal(self, strategy: str, symbol: str, timeframe: str) -> dict | None:
        raw = await self.client.get(f"signal:{strategy}:{symbol}:{timeframe}")
        if raw is None:
            return None
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            logger.warning("malformed signal payload for %s:%s:%s", strategy, symbol, timeframe)
            return None

    async def discover_strategies(self, symbol: str, timeframe: str) -> set[str]:
        """SCAN for any `signal:{strategy}:{symbol}:{timeframe}` key, returning strategy names."""
        pattern = f"signal:*:{symbol}:{timeframe}"
        strategies: set[str] = set()
        async for key in self.client.scan_iter(match=pattern):
            parts = key.split(":")
            # signal:{strategy}:{symbol}:{timeframe} -> at least 4 parts; strategy name
            # itself may contain no colons by convention, so parts[1] is reliable.
            if len(parts) >= 4:
                strategies.add(parts[1])
        return strategies

    async def collect_all_raw_signals(self, symbol: str, timeframe: str) -> dict[str, dict]:
        strategy_names = set(self.settings.STRATEGY_REGISTRY)
        strategy_names |= await self.discover_strategies(symbol, timeframe)

        results: dict[str, dict] = {}
        for strategy in strategy_names:
            raw = await self.get_raw_signal(strategy, symbol, timeframe)
            if raw is not None:
                results[strategy] = raw
        return results

    # --- Regime read --------------------------------------------------------------

    async def get_regime(self, symbol: str, timeframe: str) -> RegimeRef | None:
        raw = await self.client.get(f"regime:{symbol}:{timeframe}")
        if raw is None:
            return None
        try:
            data = json.loads(raw)
            return RegimeRef(
                regime=data["regime"],
                confidence=data.get("confidence", 0.0),
                sub_regimes=data.get("sub_regimes", []),
                timestamp=data["timestamp"],
            )
        except Exception:  # noqa: BLE001
            logger.warning("malformed regime payload for %s:%s", symbol, timeframe)
            return None

    # --- Aggregated signal cache + pub/sub -----------------------------------------

    def _aggregated_key(self, symbol: str, timeframe: str) -> str:
        return f"{self.settings.REDIS_KEY_PREFIX_AGGREGATED}:{symbol}:{timeframe}"

    def _aggregated_channel(self, symbol: str) -> str:
        return f"{self.settings.REDIS_CHANNEL_AGGREGATED_PREFIX}:{symbol}"

    async def get_cached_result(self, symbol: str, timeframe: str) -> AggregatedSignalResult | None:
        raw = await self.client.get(self._aggregated_key(symbol, timeframe))
        if raw is None:
            return None
        try:
            return AggregatedSignalResult.model_validate_json(raw)
        except Exception:  # noqa: BLE001
            logger.exception("failed to deserialize cached aggregated signal for %s:%s", symbol, timeframe)
            return None

    async def set_cached_result(self, result: AggregatedSignalResult, ttl_seconds: int = 900) -> None:
        key = self._aggregated_key(result.symbol, result.timeframe)
        await self.client.set(key, result.model_dump_json(), ex=ttl_seconds)

    async def publish_result(self, result: AggregatedSignalResult) -> None:
        channel = self._aggregated_channel(result.symbol)
        payload = result.model_dump(mode="json")
        await self.client.publish(channel, json.dumps(payload, default=_json_default))

    # --- Trigger subscriptions ------------------------------------------------------

    async def subscribe_triggers(self, symbols: list[str]) -> aioredis.client.PubSub:
        """Subscribes to both signal-arrival and regime-change channels for each symbol."""
        pubsub = self.client.pubsub()
        channels = []
        for symbol in symbols:
            channels.append(f"{self.settings.REDIS_CHANNEL_SIGNALS_PREFIX}:{symbol}")
            channels.append(f"{self.settings.REDIS_CHANNEL_REGIME_PREFIX}:{symbol}")
        await pubsub.subscribe(*channels)
        logger.info("subscribed to trigger channels: %s", channels)
        return pubsub

    async def listen(self, pubsub: aioredis.client.PubSub) -> AsyncIterator[dict]:
        async for message in pubsub.listen():
            if message.get("type") != "message":
                continue
            try:
                yield {"channel": message["channel"], "data": json.loads(message["data"])}
            except (TypeError, json.JSONDecodeError):
                logger.warning("dropped malformed pub/sub message on %s", message.get("channel"))
                continue

    # --- Weight cache invalidation channel ------------------------------------------

    async def publish_weights_updated(self, regime: str) -> None:
        await self.client.publish(
            self.settings.REDIS_CHANNEL_WEIGHTS_UPDATED, json.dumps({"regime": regime})
        )

    async def subscribe_weights_updated(self) -> aioredis.client.PubSub:
        pubsub = self.client.pubsub()
        await pubsub.subscribe(self.settings.REDIS_CHANNEL_WEIGHTS_UPDATED)
        return pubsub
