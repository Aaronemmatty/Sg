"""
SSE (Server-Sent Events) stream for live portfolio events.

GET /portfolio/stream — yields PortfolioEvent JSON for dashboard consumption.
Same SSE fan-out pattern as execution_engine_service's /execution/stream.
"""
from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, Depends
from sse_starlette.sse import EventSourceResponse

from app.auth import CurrentUser, get_current_user
from app.core.logging import get_logger

log = get_logger(__name__)
router = APIRouter(tags=["stream"])

# Fan-out queues — one per SSE connection
_sse_queues: list[asyncio.Queue] = []


def broadcast_portfolio_event(payload: dict) -> None:
    """Called from background tasks to fan-out to all SSE subscribers."""
    data = json.dumps(payload)
    for q in list(_sse_queues):
        try:
            q.put_nowait(data)
        except asyncio.QueueFull:
            log.warning("sse_queue_full_dropping_event")


@router.get("/portfolio/stream")
async def portfolio_stream(_user: CurrentUser = Depends(get_current_user)):
    """
    Live portfolio event stream (SSE).
    Yields position updates, snapshot events, and MTM refreshes.
    """
    q: asyncio.Queue = asyncio.Queue(maxsize=500)
    _sse_queues.append(q)

    async def generator():
        try:
            while True:
                try:
                    data = await asyncio.wait_for(q.get(), timeout=30.0)
                    yield {"event": "portfolio_event", "data": data}
                except asyncio.TimeoutError:
                    yield {"event": "heartbeat", "data": "{}"}
        finally:
            if q in _sse_queues:
                _sse_queues.remove(q)

    return EventSourceResponse(generator())
