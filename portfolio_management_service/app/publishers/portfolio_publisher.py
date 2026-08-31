"""
Portfolio Event Publisher.

Publishes PortfolioEvent messages to sg:portfolio:events for dashboard
and downstream service consumption. Non-critical: publish errors are
logged but never propagate to callers.
"""
from __future__ import annotations

import redis.asyncio as redis

from app.core.config import settings
from app.core.logging import get_logger
from app.models.domain import PortfolioEvent

log = get_logger(__name__)

_redis_client: redis.Redis | None = None


def set_redis_client(client: redis.Redis) -> None:
    global _redis_client
    _redis_client = client


async def publish_portfolio_event(event: PortfolioEvent) -> None:
    if _redis_client is None:
        log.warning("portfolio_publisher_no_redis_client")
        return
    try:
        await _redis_client.publish(
            settings.redis_portfolio_events_channel,
            event.model_dump_json(),
        )
    except Exception:
        log.exception(
            "portfolio_event_publish_failed",
            event_type=event.event_type.value,
        )
