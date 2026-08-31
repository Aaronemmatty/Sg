"""
Reconciliation safety-net.

The post-submit poller (worker.py) handles the common case immediately after
submission. This loop runs continuously in the background and re-checks every
order still in a non-terminal state (SUBMITTED / ACKNOWLEDGED /
PARTIALLY_FILLED) against broker_service, catching:
  - orders whose post-submit poller task died/crashed/was lost on restart
  - orders that sat ACKNOWLEDGED for a long time (e.g. limit order resting)
  - any drift between local and broker state generally
"""
from __future__ import annotations

import asyncio

from app import db, fill_processor
from app.clients import BrokerServiceClient, BrokerServiceError
from app.config import settings
from app.logging_config import get_logger

log = get_logger(__name__)


async def reconciliation_loop(broker_client: BrokerServiceClient, stop_event: asyncio.Event) -> None:
    log.info("reconciliation_loop_started", interval_s=settings.reconciliation_interval_seconds)
    while not stop_event.is_set():
        try:
            await _run_once(broker_client)
        except Exception:
            log.exception("reconciliation_cycle_failed")

        try:
            await asyncio.wait_for(stop_event.wait(), timeout=settings.reconciliation_interval_seconds)
        except asyncio.TimeoutError:
            pass
    log.info("reconciliation_loop_stopped")


async def _run_once(broker_client: BrokerServiceClient) -> None:
    orders = await db.list_non_terminal_orders()
    if not orders:
        return
    log.debug("reconciliation_cycle", order_count=len(orders))

    for order in orders:
        if not order.broker_order_id:
            continue  # not yet submitted far enough to have a broker id
        try:
            payload = await broker_client.get_order_status(order.broker_order_id)
        except BrokerServiceError:
            log.warning("reconciliation_status_fetch_failed", order_id=str(order.order_id))
            continue
        except Exception:
            log.exception("reconciliation_status_fetch_error", order_id=str(order.order_id))
            continue

        try:
            await fill_processor.apply_broker_status(order, payload, source="reconciliation")
        except Exception:
            log.exception("reconciliation_apply_status_failed", order_id=str(order.order_id))
            continue
