from __future__ import annotations

import asyncio
import json
import logging
from typing import Optional

import redis.asyncio as redis

from app.config import settings
from app.models import ExecutionEvent, format_execution_notification
from app.telegram_client import TelegramClient

logger = logging.getLogger("notification_service.consumer")


class ExecutionConsumer:
    """
    Subscribes to Redis pub/sub pattern `sg:executions:*` and asynchronously
    dispatches Telegram alerts on fill events.
    """

    def __init__(
        self,
        redis_url: Optional[str] = None,
        telegram_client: Optional[TelegramClient] = None,
    ) -> None:
        self.redis_url = redis_url or settings.REDIS_URL
        self.telegram = telegram_client or TelegramClient()
        self._redis: Optional[redis.Redis] = None
        self._pubsub: Optional[redis.client.PubSub] = None
        self._bg_tasks: set[asyncio.Task] = set()

    async def connect(self) -> None:
        self._redis = redis.from_url(self.redis_url, decode_responses=True)
        await self._redis.ping()
        logger.info("redis_connected", extra={"url": self.redis_url})

    async def close(self) -> None:
        if self._pubsub:
            await self._pubsub.close()
        if self._redis:
            await self._redis.close()
        await self.telegram.close()

        # Wait briefly for in-flight notification tasks
        if self._bg_tasks:
            done, pending = await asyncio.wait(self._bg_tasks, timeout=2.0)
            for t in pending:
                t.cancel()

    async def run(self, stop_event: asyncio.Event) -> None:
        if not self._redis:
            await self.connect()

        self._pubsub = self._redis.pubsub()
        await self._pubsub.psubscribe(settings.REDIS_EXECUTIONS_PATTERN)
        logger.info("subscribed_to_executions", extra={"pattern": settings.REDIS_EXECUTIONS_PATTERN})

        async for message in self._pubsub.listen():
            if stop_event.is_set():
                break

            if message["type"] != "pmessage":
                continue

            raw = message["data"]
            try:
                payload = json.loads(raw) if isinstance(raw, str) else raw
                event = ExecutionEvent.model_validate(payload)
            except Exception as exc:
                logger.error(
                    "malformed_execution_event_skipped",
                    extra={"error": str(exc), "raw": str(raw)[:300]},
                )
                continue

            await self.process_event(event)

        logger.info("execution_consumer_stopped")

    async def process_event(self, event: ExecutionEvent) -> None:
        """Processes an execution event; dispatches notification in background if fill."""
        if not event.is_fill:
            return

        text = format_execution_notification(event)

        # Dispatch non-blocking background task so pub/sub consumer never stalls
        task = asyncio.create_task(self._send_background(text, event.symbol))
        self._bg_tasks.add(task)
        task.add_done_callback(self._bg_tasks.discard)

    async def _send_background(self, text: str, symbol: str) -> None:
        try:
            delivered = await self.telegram.send_message(text)
            if delivered:
                logger.info("notification_sent_successfully", extra={"symbol": symbol})
            else:
                logger.warning("notification_delivery_failed", extra={"symbol": symbol})
        except Exception as exc:
            logger.error("notification_background_task_error", extra={"error": str(exc), "symbol": symbol})
