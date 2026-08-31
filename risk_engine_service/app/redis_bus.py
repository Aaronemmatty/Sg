from __future__ import annotations

import json
from typing import Any, AsyncIterator

import redis.asyncio as redis

from app.logging_setup import get_logger

log = get_logger(module="redis_bus")


class RedisBus:
    def __init__(self, url: str) -> None:
        self._url = url
        self.client: redis.Redis | None = None

    async def connect(self) -> None:
        self.client = redis.from_url(self._url, decode_responses=True)
        await self.client.ping()
        log.info("redis_connected")

    async def disconnect(self) -> None:
        if self.client:
            await self.client.close()
            log.info("redis_disconnected")

    async def publish_json(self, channel: str, payload: dict[str, Any]) -> None:
        assert self.client is not None
        await self.client.publish(channel, json.dumps(payload, default=str))

    async def set_hot_key(self, key: str, payload: dict[str, Any], ttl_seconds: int | None = None) -> None:
        assert self.client is not None
        value = json.dumps(payload, default=str)
        if ttl_seconds:
            await self.client.set(key, value, ex=ttl_seconds)
        else:
            await self.client.set(key, value)

    async def get_hot_key(self, key: str) -> dict[str, Any] | None:
        assert self.client is not None
        raw = await self.client.get(key)
        if raw is None:
            return None
        return json.loads(raw)

    async def subscribe_pattern(self, pattern: str) -> AsyncIterator[dict[str, Any]]:
        assert self.client is not None
        pubsub = self.client.pubsub()
        await pubsub.psubscribe(pattern)
        log.info("subscribed", pattern=pattern)
        try:
            async for message in pubsub.listen():
                if message is None:
                    continue
                if message.get("type") not in ("pmessage", "message"):
                    continue
                try:
                    data = json.loads(message["data"])
                except (TypeError, json.JSONDecodeError):
                    continue
                data["_channel"] = message.get("channel")
                yield data
        finally:
            await pubsub.punsubscribe(pattern)
            await pubsub.close()
