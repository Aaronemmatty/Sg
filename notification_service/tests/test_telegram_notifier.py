from __future__ import annotations

import asyncio
import json
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from app.config import Settings
from app.execution_consumer import ExecutionConsumer
from app.models import (
    ExecutionEvent,
    ExecutionEventType,
    TradeAction,
    format_execution_notification,
)
from app.telegram_client import TelegramClient


# ─────────────────────────────────────────────────────────────────────────────
# 1. Successful Notification Send & Unmistakable Tagging ([LIVE] vs [PAPER])
# ─────────────────────────────────────────────────────────────────────────────

def test_paper_execution_formatting():
    event = ExecutionEvent(
        event_type=ExecutionEventType.ORDER_FILLED,
        order_id=uuid.uuid4(),
        symbol="RELIANCE",
        action=TradeAction.BUY,
        state="FILLED",
        quantity=50,
        filled_quantity=50,
        avg_fill_price_inr=2950.25,
        broker_order_id="PAPER-A1B2C3D4",
        slippage_bps=2.1,
    )
    assert event.is_paper is True
    assert event.is_fill is True

    text = format_execution_notification(event)
    assert "[PAPER]" in text
    assert "[LIVE]" not in text
    assert "🟢" in text
    assert "BUY" in text
    assert "50" in text
    assert "RELIANCE" in text
    assert "₹2,950.25" in text
    assert "PAPER-A1B2C3D4" in text
    assert "2.1 bps" in text


def test_live_execution_formatting():
    event = ExecutionEvent(
        event_type=ExecutionEventType.ORDER_FILLED,
        order_id=uuid.uuid4(),
        symbol="INFY",
        action=TradeAction.SELL,
        state="FILLED",
        quantity=100,
        filled_quantity=100,
        avg_fill_price_inr=1825.50,
        broker_order_id="240903000045678",  # Real numeric Kite broker ID
        slippage_bps=0.0,
    )
    assert event.is_paper is False
    assert event.is_fill is True

    text = format_execution_notification(event)
    assert "[LIVE]" in text
    assert "[PAPER]" not in text
    assert "🔴" in text
    assert "SELL" in text
    assert "100" in text
    assert "INFY" in text
    assert "₹1,825.50" in text
    assert "240903000045678" in text


@pytest.mark.asyncio
async def test_telegram_client_send_message_success():
    client = TelegramClient(bot_token="test_bot_token", chat_id="123456789")

    mock_response = httpx.Response(
        status_code=200,
        json={"ok": True, "result": {"message_id": 999}},
        request=httpx.Request("POST", "https://api.telegram.org/bot/test/sendMessage"),
    )

    with patch.object(httpx.AsyncClient, "post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = mock_response
        delivered = await client.send_message("<b>[PAPER] Alert</b>")

        assert delivered is True
        assert mock_post.await_count == 1
        args, kwargs = mock_post.call_args
        assert kwargs["json"]["chat_id"] == "123456789"
        assert kwargs["json"]["text"] == "<b>[PAPER] Alert</b>"
        assert kwargs["json"]["parse_mode"] == "HTML"

    await client.close()


# ─────────────────────────────────────────────────────────────────────────────
# 2. Resilient Error Handling (Outage / Rate Limit / Timeout Does Not Crash)
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_telegram_client_network_failure_retries_and_gracefully_fails():
    client = TelegramClient(
        bot_token="test_bot_token",
        chat_id="123456789",
        timeout_seconds=0.1,
        max_retries=3,
        backoff_base_s=0.01,
    )

    with patch.object(httpx.AsyncClient, "post", new_callable=AsyncMock) as mock_post:
        mock_post.side_effect = httpx.ConnectError("Connection refused by Telegram endpoint")

        # Must NOT raise exception to caller; must return False and log
        delivered = await client.send_message("Test message")
        assert delivered is False
        assert mock_post.await_count == 3

    await client.close()


@pytest.mark.asyncio
async def test_telegram_client_handles_rate_limit_429():
    client = TelegramClient(
        bot_token="test_bot_token",
        chat_id="123456789",
        max_retries=2,
        backoff_base_s=0.01,
    )

    mock_429 = httpx.Response(
        status_code=429,
        json={"ok": False, "parameters": {"retry_after": 0.01}},
        request=httpx.Request("POST", "https://api.telegram.org/bot/test/sendMessage"),
    )
    mock_200 = httpx.Response(
        status_code=200,
        json={"ok": True, "result": {"message_id": 1000}},
        request=httpx.Request("POST", "https://api.telegram.org/bot/test/sendMessage"),
    )

    with patch.object(httpx.AsyncClient, "post", new_callable=AsyncMock) as mock_post:
        mock_post.side_effect = [mock_429, mock_200]

        delivered = await client.send_message("Test retry on rate limit")
        assert delivered is True
        assert mock_post.await_count == 2

    await client.close()


@pytest.mark.asyncio
async def test_execution_consumer_does_not_crash_on_failed_telegram_delivery():
    mock_telegram = AsyncMock(spec=TelegramClient)
    mock_telegram.send_message = AsyncMock(return_value=False)

    consumer = ExecutionConsumer(telegram_client=mock_telegram)

    fill_event = ExecutionEvent(
        event_type=ExecutionEventType.ORDER_FILLED,
        order_id=uuid.uuid4(),
        symbol="TCS",
        action=TradeAction.BUY,
        state="FILLED",
        quantity=10,
        filled_quantity=10,
        avg_fill_price_inr=4100.0,
        broker_order_id="PAPER-9999",
    )

    # Process event must be smooth and non-blocking
    await consumer.process_event(fill_event)
    await asyncio.sleep(0.05)  # Let background task complete

    assert mock_telegram.send_message.await_count == 1


# ─────────────────────────────────────────────────────────────────────────────
# 3. Verification of ZERO Inbound Telegram Commands / Capability
# ─────────────────────────────────────────────────────────────────────────────

def test_strictly_outbound_architecture():
    """
    Guarantees that no incoming command processing exists in notification_service:
    1. TelegramClient has NO `getUpdates`, `listen`, `poll`, or `webhook` methods.
    2. FastAPI application has NO webhook route matching telegram update endpoints.
    3. No command parsers or dispatchers exist.
    """
    client = TelegramClient()
    prohibited_methods = [
        "get_updates",
        "getupdates",
        "poll",
        "listen",
        "webhook",
        "set_webhook",
        "handle_command",
        "process_update",
    ]
    for method in prohibited_methods:
        assert not hasattr(client, method), f"TelegramClient must not contain '{method}'"

    from app.main import app
    routes = [r.path for r in app.routes]
    assert "/webhook" not in routes
    assert "/telegram/webhook" not in routes
    assert "/bot" not in routes
    # Only health and test endpoints exist
    assert "/health" in routes
    assert "/v1/notifications/test" in routes
