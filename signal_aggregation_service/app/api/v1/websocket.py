"""Real-time aggregated-signal push over WebSocket, backed by sg:aggregated_signal:{symbol}."""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect

from app.api.deps import get_redis
from app.services.redis_client import AggregationRedisClient

logger = logging.getLogger(__name__)
router = APIRouter()


@router.websocket("/ws/signal/{symbol}")
async def aggregated_signal_stream(
    websocket: WebSocket,
    symbol: str,
    redis_client: AggregationRedisClient = Depends(get_redis),
):
    await websocket.accept()
    pubsub = redis_client.client.pubsub()
    channel = f"{redis_client.settings.REDIS_CHANNEL_AGGREGATED_PREFIX}:{symbol}"
    await pubsub.subscribe(channel)
    try:
        async for message in pubsub.listen():
            if message.get("type") != "message":
                continue
            await websocket.send_text(message["data"])
    except WebSocketDisconnect:
        logger.info("client disconnected from aggregated signal stream for %s", symbol)
    finally:
        await pubsub.unsubscribe(channel)
        await pubsub.aclose()
