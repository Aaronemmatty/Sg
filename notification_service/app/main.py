from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import Depends, FastAPI, HTTPException
from pydantic import BaseModel

from app.auth import CurrentUser, get_current_user
from app.config import settings
from app.execution_consumer import ExecutionConsumer
from app.telegram_client import TelegramClient

logging.basicConfig(level=settings.LOG_LEVEL)
logger = logging.getLogger("notification_service.main")

consumer: ExecutionConsumer | None = None
consumer_task: asyncio.Task | None = None
stop_event = asyncio.Event()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    global consumer, consumer_task, stop_event
    logger.info("starting_notification_service", extra={"port": settings.SERVICE_PORT})
    stop_event.clear()
    consumer = ExecutionConsumer()
    consumer_task = asyncio.create_task(consumer.run(stop_event))

    yield

    logger.info("stopping_notification_service")
    stop_event.set()
    if consumer:
        await consumer.close()
    if consumer_task:
        consumer_task.cancel()
        try:
            await consumer_task
        except asyncio.CancelledError:
            pass


app = FastAPI(
    title="SG Notification Service",
    description="Dedicated outbound-only notification service for SG Trading Platform.",
    version="1.0.0",
    lifespan=lifespan,
)


@app.get("/health")
async def health():
    is_tg_configured = bool(settings.TELEGRAM_BOT_TOKEN and settings.TELEGRAM_CHAT_ID)
    return {
        "status": "ok",
        "service": settings.SERVICE_NAME,
        "version": "1.0.0",
        "telegram_configured": is_tg_configured,
        "subscribed_pattern": settings.REDIS_EXECUTIONS_PATTERN,
    }


class TestAlertRequest(BaseModel):
    text: str = "[PAPER] 🧪 Test alert from SG Trading Platform Notification Service"


@app.post("/v1/notifications/test")
async def send_test_alert(
    body: TestAlertRequest,
    _user: CurrentUser = Depends(get_current_user),
):
    """Admin utility endpoint to test Telegram bot delivery."""
    if not settings.TELEGRAM_BOT_TOKEN or not settings.TELEGRAM_CHAT_ID:
        raise HTTPException(
            status_code=400,
            detail="TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID is not configured in notification_service/.env",
        )

    client = TelegramClient()
    try:
        delivered = await client.send_message(body.text)
        if not delivered:
            raise HTTPException(status_code=502, detail="Failed to deliver Telegram notification.")
        return {"status": "ok", "delivered": True}
    finally:
        await client.close()
