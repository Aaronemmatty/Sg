from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query

from app import db, state_machine
from app.auth import CurrentUser, get_current_user, require_role
from app.clients import BrokerServiceClient, BrokerServiceError, broker_client
from app.events import event_bus
from app.logging_config import get_logger
from app.models import ExecutionEvent, OrderState

log = get_logger(__name__)

router = APIRouter(prefix="/orders", tags=["orders"])


@router.get("")
async def list_orders(
    symbol: str | None = Query(default=None),
    state: OrderState | None = Query(default=None),
    limit: int = Query(default=100, le=500),
    offset: int = Query(default=0, ge=0),
    _user: CurrentUser = Depends(get_current_user),
):
    orders = await db.list_orders(symbol=symbol, state=state, limit=limit, offset=offset)
    return {"orders": [o.model_dump(mode="json") for o in orders], "count": len(orders)}


@router.get("/{order_id}")
async def get_order(order_id: uuid.UUID, _user: CurrentUser = Depends(get_current_user)):
    order = await db.get_order(order_id)
    if order is None:
        raise HTTPException(status_code=404, detail="Order not found")
    return order.model_dump(mode="json")


@router.get("/{order_id}/executions")
async def get_order_executions(order_id: uuid.UUID, _user: CurrentUser = Depends(get_current_user)):
    order = await db.get_order(order_id)
    if order is None:
        raise HTTPException(status_code=404, detail="Order not found")
    executions = await db.list_executions_for_order(order_id)
    return {"order_id": str(order_id), "executions": [e.model_dump(mode="json") for e in executions]}


@router.get("/{order_id}/audit")
async def get_order_audit(order_id: uuid.UUID, _user: CurrentUser = Depends(get_current_user)):
    order = await db.get_order(order_id)
    if order is None:
        raise HTTPException(status_code=404, detail="Order not found")
    logs = await db.list_audit_logs_for_order(order_id)
    return {"order_id": str(order_id), "audit_logs": logs}


@router.post("/{order_id}/cancel")
async def cancel_order(
    order_id: uuid.UUID,
    user: CurrentUser = Depends(require_role("risk_officer")),
):
    """Manual cancel override. Role-gated to risk_officer, matching the
    risk_engine pattern (kill-switch reset / policy edits are also
    risk_officer-only)."""
    order = await db.get_order(order_id)
    if order is None:
        raise HTTPException(status_code=404, detail="Order not found")

    if state_machine.is_terminal(order.state):
        raise HTTPException(status_code=409, detail=f"Order already in terminal state {order.state.value}")

    if order.state == OrderState.HELD:
        target = state_machine.transition(order.state, OrderState.CANCELLED)
        updated = await db.update_order_state(order.order_id, order.state, target, actor=user.username, reason="manual_cancel")
        await db.mark_held_intent_resolved(order.intent_id)
    elif order.broker_order_id:
        try:
            await broker_client.cancel_order(order.broker_order_id)
        except BrokerServiceError as exc:
            raise HTTPException(status_code=502, detail=f"Broker cancel failed: {exc}")
        target = state_machine.transition(order.state, OrderState.CANCELLED)
        updated = await db.update_order_state(order.order_id, order.state, target, actor=user.username, reason="manual_cancel")
    else:
        raise HTTPException(status_code=409, detail="Order has no broker_order_id yet; cannot cancel mid-routing")

    await event_bus.publish(
        ExecutionEvent(
            event_type="ORDER_CANCELLED",
            order_id=updated.order_id, intent_id=updated.intent_id, correlation_id=updated.correlation_id,
            symbol=updated.symbol, action=updated.action, state=updated.state,
            reason=f"manual_cancel_by:{user.username}",
        )
    )
    return updated.model_dump(mode="json")
