from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, Request
from sse_starlette.sse import EventSourceResponse

from app.auth import CurrentUser, get_current_user
from app.events import event_bus
from app.logging_config import get_logger

log = get_logger(__name__)

router = APIRouter(tags=["stream"])


@router.get("/execution/stream")
async def execution_stream(request: Request, _user: CurrentUser = Depends(get_current_user)):
    """SSE stream of order lifecycle events (non order-flow-critical — same
    spirit as risk_engine's /risk/stream feeding the dashboard, not used by
    any downstream service that depends on guaranteed delivery)."""
    queue = event_bus.subscribe_sse()

    async def event_generator():
        try:
            while True:
                if await request.is_disconnected():
                    break
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=15.0)
                    yield {"event": event.event_type, "data": event.model_dump_json()}
                except asyncio.TimeoutError:
                    yield {"event": "heartbeat", "data": "{}"}
        finally:
            event_bus.unsubscribe_sse(queue)

    return EventSourceResponse(event_generator())
