"""
WebSocket streaming endpoint.

Clients connect and receive real-time ticks and candles via Redis pub/sub.

Protocol:
  Client → Server:
    {"action": "subscribe",   "symbols": ["NSE:RELIANCE"], "channels": ["tick", "candle:1m"]}
    {"action": "unsubscribe", "symbols": ["NSE:RELIANCE"]}
    {"action": "ping"}

  Server → Client:
    {"type": "tick",   "data": {...}}
    {"type": "candle", "data": {...}}
    {"type": "error",  "message": "..."}
    {"type": "pong"}
    {"type": "subscribed", "symbols": [...]}
"""

from __future__ import annotations

import asyncio
import json
from typing import Optional

import redis.asyncio as aioredis
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, status

from app.core.config import get_settings
from app.core.logging import get_logger
from app.core.redis import get_redis

settings = get_settings()
log = get_logger(__name__)
router = APIRouter(tags=["WebSocket"])


@router.websocket("/ws/market")
async def market_websocket(websocket: WebSocket) -> None:
    await websocket.accept()
    client_id = id(websocket)
    log.info("ws_client_connected", client_id=client_id)

    pubsub: Optional[aioredis.client.PubSub] = None
    listen_task: Optional[asyncio.Task] = None

    try:
        r = await get_redis()
        pubsub = r.pubsub()

        # Task: forward Redis pub/sub messages to WebSocket
        listen_task = asyncio.create_task(
            _listen_and_forward(pubsub, websocket, client_id),
            name=f"ws-forward-{client_id}",
        )

        # Main loop: handle client messages
        while True:
            try:
                raw = await asyncio.wait_for(websocket.receive_text(), timeout=30.0)
            except asyncio.TimeoutError:
                # Send keepalive ping
                await websocket.send_json({"type": "ping"})
                continue

            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                await websocket.send_json({"type": "error", "message": "Invalid JSON"})
                continue

            action = msg.get("action")

            if action == "subscribe":
                symbols  = msg.get("symbols", [])
                channels = msg.get("channels", ["tick", "candle:1m"])
                patterns = _build_patterns(symbols, channels)
                if patterns:
                    await pubsub.psubscribe(*patterns)
                    await websocket.send_json({
                        "type": "subscribed",
                        "symbols": symbols,
                        "channels": channels,
                    })

            elif action == "unsubscribe":
                symbols = msg.get("symbols", [])
                patterns = _build_patterns(symbols, ["tick", "candle:1m",
                                                     "candle:3m", "candle:5m",
                                                     "candle:15m", "candle:30m",
                                                     "candle:1h", "candle:4h", "candle:1D"])
                if patterns:
                    await pubsub.punsubscribe(*patterns)
                await websocket.send_json({"type": "unsubscribed", "symbols": symbols})

            elif action == "ping":
                await websocket.send_json({"type": "pong"})

            else:
                await websocket.send_json({"type": "error", "message": f"Unknown action: {action}"})

    except WebSocketDisconnect:
        log.info("ws_client_disconnected", client_id=client_id)
    except Exception as exc:
        log.error("ws_error", client_id=client_id, error=str(exc))
    finally:
        if listen_task:
            listen_task.cancel()
        if pubsub:
            await pubsub.close()


async def _listen_and_forward(
    pubsub: aioredis.client.PubSub,
    websocket: WebSocket,
    client_id: int,
) -> None:
    """Forward Redis pub/sub messages to the WebSocket client."""
    try:
        async for message in pubsub.listen():
            if message["type"] not in ("pmessage", "message"):
                continue

            channel = message.get("channel", "") or message.get("pattern", "")
            data_raw = message.get("data", "")

            try:
                data = json.loads(data_raw)
            except (json.JSONDecodeError, TypeError):
                continue

            # Determine message type from channel name
            channel_str = channel if isinstance(channel, str) else channel.decode()
            if ":tick:" in channel_str:
                msg_type = "tick"
            elif ":candle:" in channel_str:
                msg_type = "candle"
            elif ":status" in channel_str:
                msg_type = "status"
            else:
                msg_type = "data"

            try:
                await websocket.send_json({"type": msg_type, "data": data})
            except Exception:
                break   # Client disconnected

    except asyncio.CancelledError:
        pass
    except Exception as exc:
        log.error("ws_forward_error", client_id=client_id, error=str(exc))


def _build_patterns(symbols: list[str], channels: list[str]) -> list[str]:
    """Build Redis channel patterns for given symbols and channel types."""
    prefix = settings.REDIS_CHANNEL_PREFIX
    patterns = []
    for sym in symbols:
        full_sym = sym if ":" in sym else f"NSE:{sym}"
        for ch in channels:
            if ch == "tick":
                patterns.append(f"{prefix}:tick:{full_sym}")
            elif ch.startswith("candle:"):
                tf = ch.split(":", 1)[1]
                patterns.append(f"{prefix}:candle:{full_sym}:{tf}")
    return patterns
