"""Real-time regime push over WebSocket, backed by the sg:regime:{symbol} Redis channel."""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect

from app.api.deps import get_redis
from app.services.redis_client import RegimeRedisClient

logger = logging.getLogger(__name__)
router = APIRouter()


@router.websocket("/ws/regime/{symbol}")
async def regime_stream(
    websocket: WebSocket,
    symbol: str,
    redis_client: RegimeRedisClient = Depends(get_redis),
):
    """
    Streams every `regime_update`/`regime_change` event published for `symbol`.
    No timeframe filter at the protocol level — the client filters by `timeframe` in the
    payload if it only cares about one, since a symbol's regime channel carries all
    timeframes that get recomputed for it.
    """
    await websocket.accept()
    pubsub = redis_client.client.pubsub()
    channel = f"{redis_client.settings.REDIS_CHANNEL_REGIME_PREFIX}:{symbol}"
    await pubsub.subscribe(channel)
    try:
        async for message in pubsub.listen():
            if message.get("type") != "message":
                continue
            await websocket.send_text(message["data"])
    except WebSocketDisconnect:
        logger.info("client disconnected from regime stream for %s", symbol)
    finally:
        await pubsub.unsubscribe(channel)
        await pubsub.aclose()
