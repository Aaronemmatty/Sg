from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import StrEnum
from typing import Optional
from zoneinfo import ZoneInfo

from pydantic import BaseModel, Field

IST = ZoneInfo("Asia/Kolkata")


class TradeAction(StrEnum):
    BUY = "BUY"
    SELL = "SELL"


class ExecutionEventType(StrEnum):
    ORDER_SUBMITTED = "ORDER_SUBMITTED"
    ORDER_ACKNOWLEDGED = "ORDER_ACKNOWLEDGED"
    ORDER_PARTIALLY_FILLED = "ORDER_PARTIALLY_FILLED"
    ORDER_FILLED = "ORDER_FILLED"
    ORDER_REJECTED = "ORDER_REJECTED"
    ORDER_CANCELLED = "ORDER_CANCELLED"
    ORDER_EXPIRED = "ORDER_EXPIRED"
    ORDER_FAILED = "ORDER_FAILED"


class ExecutionEvent(BaseModel):
    """
    Inbound execution event published to sg:executions:{symbol}
    by execution_engine_service (8008).
    """
    event_type: str
    order_id: uuid.UUID
    intent_id: Optional[uuid.UUID] = None
    correlation_id: Optional[uuid.UUID] = None
    symbol: str
    action: TradeAction
    state: str
    quantity: Optional[int] = None
    filled_quantity: int = 0
    avg_fill_price_inr: Optional[float] = None
    slippage_bps: Optional[float] = None
    broker_order_id: Optional[str] = None
    reason: Optional[str] = None
    emitted_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def is_paper(self) -> bool:
        """Determines whether the execution occurred in paper simulation vs live broker."""
        if self.broker_order_id and "PAPER" in self.broker_order_id.upper():
            return True
        return False

    @property
    def is_fill(self) -> bool:
        return self.event_type in (
            ExecutionEventType.ORDER_FILLED,
            ExecutionEventType.ORDER_PARTIALLY_FILLED,
        )


def format_execution_notification(event: ExecutionEvent) -> str:
    """
    Formats an ExecutionEvent into an unmistakable Telegram alert.
    Strictly distinguishes [PAPER] vs [LIVE] execution mode.
    """
    mode_tag = "[PAPER]" if event.is_paper else "[LIVE]"
    side_emoji = "🟢" if event.action == TradeAction.BUY else "🔴"
    side_text = event.action.value.upper()

    price_str = (
        f"₹{event.avg_fill_price_inr:,.2f}"
        if event.avg_fill_price_inr is not None
        else "N/A"
    )

    qty_str = str(event.filled_quantity if event.filled_quantity > 0 else (event.quantity or 0))

    # Format timestamp in IST (Indian Standard Time)
    emitted_ist = event.emitted_at.astimezone(IST)
    ts_str = emitted_ist.strftime("%Y-%m-%d %H:%M:%S IST")

    order_ref = event.broker_order_id or str(event.order_id)[:8]
    status_text = "PARTIALLY FILLED" if event.event_type == ExecutionEventType.ORDER_PARTIALLY_FILLED else "FILLED"

    lines = [
        f"<b>{mode_tag} {side_emoji} {side_text} {qty_str} {event.symbol} @ {price_str}</b>",
        "",
        f"• <b>Status:</b> {status_text}",
        f"• <b>Quantity:</b> {qty_str}",
        f"• <b>Avg Price:</b> {price_str}",
        f"• <b>Order Ref:</b> <code>{order_ref}</code>",
        f"• <b>Time:</b> {ts_str}",
    ]

    if event.slippage_bps is not None:
        lines.append(f"• <b>Slippage:</b> {event.slippage_bps:.1f} bps")

    return "\n".join(lines)
