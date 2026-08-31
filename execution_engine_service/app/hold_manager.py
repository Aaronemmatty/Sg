"""
RISK_HOLD handling.

*** OPEN DECISION - DEFAULT BEHAVIOR, CONFIRM WITH RISK_ENGINE OWNER ***
The handover spec explicitly left undefined what happens to RISK_HOLD
intents. The default implemented here:

  1. A RISK_HOLD RiskDecision creates an Order in HELD state (not yet
     routed/sized) plus a row in `held_intents` with an expiry
     (HOLD_MAX_AGE_SECONDS from receipt).
  2. execution_engine does NOT re-poll risk_engine to ask "is this still
     held?" — risk_engine owns that decision. If risk_engine wants a HELD
     intent re-evaluated, the expected flow is: risk_engine re-publishes the
     same intent_id to sg:risk_approved:{symbol} with status=RISK_APPROVED
     (or RISK_REJECTED) once conditions change. This module's job is only to
     promote the existing HELD order if/when that happens, or expire it.
  3. A background sweeper (see reconciliation.py / main.py lifespan) calls
     `sweep_expired_holds()` periodically; anything past its TTL is marked
     EXPIRED and the corresponding ExecutionEvent is published so
     portfolio_management_service (and dashboards) see it leave the queue.

If the real intended behavior differs (e.g. execution_engine should actively
poll a risk_engine endpoint, or should never expire holds), this module is
the single place to change.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from app import db, state_machine
from app.config import settings
from app.events import event_bus
from app.logging_config import get_logger
from app.metrics import held_intents_expired_total
from app.models import ExecutionEvent, Order, OrderState, RiskDecision

log = get_logger(__name__)


async def park_held_intent(decision: RiskDecision, order: Order) -> None:
    await db.insert_held_intent(
        intent_id=decision.intent_id,
        order_id=order.order_id,
        symbol=decision.symbol,
        raw_payload=decision.model_dump(mode="json"),
    )
    log.info("intent_held", intent_id=str(decision.intent_id), symbol=decision.symbol, order_id=str(order.order_id))


async def sweep_expired_holds() -> int:
    """Mark any held_intents past their TTL as EXPIRED. Returns count swept."""
    expired = await db.list_expired_held_intents()
    for row in expired:
        order = await db.get_order(row["order_id"])
        if order is None or order.state != OrderState.HELD:
            # Already promoted/expired elsewhere; just close the held_intents row.
            await db.mark_held_intent_resolved(row["intent_id"])
            continue

        try:
            target = state_machine.transition(order.state, OrderState.EXPIRED)
        except state_machine.InvalidTransitionError:
            log.warning("hold_expiry_invalid_transition", order_id=str(order.order_id), current=order.state.value)
            continue

        updated = await db.update_order_state(
            order.order_id, order.state, target,
            actor="system", reason="hold_ttl_expired",
        )
        await db.mark_held_intent_resolved(row["intent_id"])
        held_intents_expired_total.labels(symbol=order.symbol).inc()

        await event_bus.publish(
            ExecutionEvent(
                event_type="ORDER_EXPIRED",
                order_id=updated.order_id,
                intent_id=updated.intent_id,
                correlation_id=updated.correlation_id,
                symbol=updated.symbol,
                action=updated.action,
                state=updated.state,
                reason="RISK_HOLD intent exceeded max age without resolution",
            )
        )
        log.info("held_intent_expired", order_id=str(order.order_id), symbol=order.symbol)

    return len(expired)
