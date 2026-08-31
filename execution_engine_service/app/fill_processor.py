"""
Translates a broker_service order-status payload into:
  - new Order state (via the state machine)
  - any new Execution (fill) rows
  - slippage calculation
  - outbound ExecutionEvent

*** ASSUMED BROKER STATUS PAYLOAD SHAPE (confirm against real 8003) ***
{
  "broker_order_id": "...",
  "status": "OPEN" | "COMPLETE" | "REJECTED" | "CANCELLED" | "PARTIALLY_FILLED",
  "filled_quantity": 100,
  "average_price": 1234.5,
  "rejection_reason": "..."?,
  "fills": [{"execution_id": "...", "quantity": 50, "price": 1234.0, "timestamp": "..."}]
}
This module only depends on that shape — if 8003's real contract differs,
only `_map_broker_status` needs to change.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from app import db, state_machine
from app.events import event_bus
from app.logging_config import get_logger
from app.metrics import (
    orders_filled_total,
    orders_terminal_total,
    reconciliation_mismatches_total,
    slippage_bps_histogram,
)
from app.models import Execution, ExecutionEvent, Order, OrderState
from app.slippage import compute_slippage

log = get_logger(__name__)


_BROKER_STATUS_TO_ORDER_STATE = {
    "OPEN": OrderState.ACKNOWLEDGED,
    "PARTIALLY_FILLED": OrderState.PARTIALLY_FILLED,
    "COMPLETE": OrderState.FILLED,
    "REJECTED": OrderState.REJECTED,
    "CANCELLED": OrderState.CANCELLED,
}


def _map_broker_status(payload: dict[str, Any]) -> OrderState | None:
    broker_status = payload.get("status", "").upper()
    return _BROKER_STATUS_TO_ORDER_STATE.get(broker_status)


async def apply_broker_status(order: Order, payload: dict[str, Any], *, source: str) -> Order:
    """Idempotent: safe to call repeatedly with the same or stale payload.
    `source` is 'post_submit_poll' or 'reconciliation', recorded in the audit log.
    Never raises on a malformed/unrecognized payload — logs and returns the
    order unchanged, so one bad broker response can't take down the polling
    or reconciliation loop calling this."""

    target_state = _map_broker_status(payload)
    if target_state is None:
        log.error(
            "unrecognized_broker_status", order_id=str(order.order_id),
            broker_status=payload.get("status"), source=source,
        )
        return order

    if target_state == order.state:
        # Nothing new (e.g. reconciliation re-checked an order already up to date).
        # Still process any fills we may not have recorded yet.
        await _record_new_fills(order, payload, source)
        return order

    if not state_machine.can_transition(order.state, target_state):
        # Could happen if e.g. broker reports COMPLETE while we're still ROUTING
        # locally due to a race; reconciliation should flag, not crash.
        reconciliation_mismatches_total.labels(symbol=order.symbol).inc()
        log.warning(
            "broker_state_mismatch",
            order_id=str(order.order_id),
            local_state=order.state.value,
            broker_state=target_state.value,
            source=source,
        )
        return order

    new_fills = await _record_new_fills(order, payload, source)

    extra_fields: dict[str, Any] = {}
    if "filled_quantity" in payload:
        extra_fields["filled_quantity"] = payload["filled_quantity"]
    if payload.get("average_price") is not None:
        extra_fields["avg_fill_price_inr"] = payload["average_price"]
    if target_state == OrderState.REJECTED and payload.get("rejection_reason"):
        extra_fields["last_error"] = payload["rejection_reason"]

    updated = await db.update_order_state(
        order.order_id, order.state, target_state,
        actor="system", reason=f"broker_status_update:{source}",
        detail={"broker_payload_status": payload.get("status")},
        **extra_fields,
    )

    if state_machine.is_terminal(target_state):
        orders_terminal_total.labels(state=target_state.value).inc()
        if target_state == OrderState.FILLED:
            orders_filled_total.labels(symbol=updated.symbol).inc()

    await event_bus.publish(_build_event(updated, target_state, new_fills))
    return updated


async def _record_new_fills(order: Order, payload: dict[str, Any], source: str) -> list[Execution]:
    existing = await db.list_executions_for_order(order.order_id)
    existing_broker_ids = {e.broker_execution_id for e in existing if e.broker_execution_id}

    new_fills: list[Execution] = []
    for fill in payload.get("fills", []):
        broker_execution_id = fill.get("execution_id")
        if broker_execution_id and broker_execution_id in existing_broker_ids:
            continue  # already recorded, idempotent skip

        fill_price = float(fill["price"])
        slippage_inr, slippage_bps = (None, None)
        if order.intended_price_inr:
            slippage_inr, slippage_bps = compute_slippage(order.intended_price_inr, fill_price, order.action)
            slippage_bps_histogram.observe(slippage_bps)

        execution = Execution(
            order_id=order.order_id,
            broker_execution_id=broker_execution_id,
            fill_quantity=int(fill["quantity"]),
            fill_price_inr=fill_price,
            fill_timestamp=_parse_ts(fill.get("timestamp")),
            slippage_inr=slippage_inr,
            slippage_bps=slippage_bps,
        )
        await db.insert_execution(execution)
        new_fills.append(execution)
        log.info(
            "fill_recorded", order_id=str(order.order_id), symbol=order.symbol,
            quantity=execution.fill_quantity, price=execution.fill_price_inr,
            slippage_bps=slippage_bps, source=source,
        )

    return new_fills


def _parse_ts(value: Any) -> datetime:
    if not value:
        return datetime.now(timezone.utc)
    try:
        return datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return datetime.now(timezone.utc)


def _build_event(order: Order, state: OrderState, new_fills: list[Execution]) -> ExecutionEvent:
    event_type_map = {
        OrderState.ACKNOWLEDGED: "ORDER_ACKNOWLEDGED",
        OrderState.PARTIALLY_FILLED: "ORDER_PARTIALLY_FILLED",
        OrderState.FILLED: "ORDER_FILLED",
        OrderState.REJECTED: "ORDER_REJECTED",
        OrderState.CANCELLED: "ORDER_CANCELLED",
    }
    latest_slippage_bps = new_fills[-1].slippage_bps if new_fills else None
    return ExecutionEvent(
        event_type=event_type_map.get(state, f"ORDER_{state.value}"),
        order_id=order.order_id,
        intent_id=order.intent_id,
        correlation_id=order.correlation_id,
        symbol=order.symbol,
        action=order.action,
        state=state,
        quantity=order.quantity,
        filled_quantity=order.filled_quantity,
        avg_fill_price_inr=order.avg_fill_price_inr,
        slippage_bps=latest_slippage_bps,
        broker_order_id=order.broker_order_id,
        reason=order.last_error,
    )
