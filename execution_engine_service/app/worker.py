"""
Core execution workflow.

  sg:risk_approved:{symbol}  --psubscribe-->  process_decision()
                                                 |
                              RISK_HOLD ---------+--------- RISK_APPROVED
                                 |                                |
                          park as HELD                    idempotency claim
                                 |                                |
                        (sweeper expires later)              route()  [order_router]
                                                                   |
                                                          insert Order (PENDING -> ROUTING)
                                                                   |
                                                    place_order()  [clients.BrokerServiceClient]
                                                       /                \
                                              success (ack/reject)   transient failure
                                                   |                       |
                                          update state +          one application-level retry,
                                          spawn post-submit        then FAILED if still failing
                                          poller task              (BrokerServiceClient already
                                                                     retries network failures
                                                                     internally via tenacity)
"""
from __future__ import annotations

import asyncio
import uuid

from app import db, hold_manager, state_machine, util
from app.clients import BrokerOrderRejected, BrokerOrderRequest, BrokerServiceClient, BrokerServiceError
from app.config import settings
from app.events import event_bus
from app.fill_processor import apply_broker_status
from app.logging_config import get_logger
from app.market_data_client import MarketDataClient
from app.metrics import (
    broker_call_failures_total,
    order_retry_total,
    orders_placed_total,
    orders_received_total,
    orders_terminal_total,
)
from app.models import ExecutionEvent, ExecutionStyle, Order, OrderState, RiskDecision, RiskStatus
from app.order_router import RoutingDecision, RoutingError, route
from app.redis_bus import RedisBus

log = get_logger(__name__)

MAX_APPLICATION_LEVEL_RETRIES = 1


class ExecutionWorker:
    def __init__(self, redis_bus: RedisBus, broker_client: BrokerServiceClient, market_data_client: MarketDataClient):
        self.redis_bus = redis_bus
        self.broker_client = broker_client
        self.market_data_client = market_data_client
        self._poll_tasks: set[asyncio.Task] = set()

    async def run(self, stop_event: asyncio.Event) -> None:
        log.info("execution_worker_started")
        async for decision in self.redis_bus.listen_risk_approved():
            if stop_event.is_set():
                break
            orders_received_total.labels(status=decision.status.value).inc()
            try:
                await self._dispatch(decision)
            except Exception:
                log.exception("decision_processing_failed", intent_id=str(decision.intent_id))
        log.info("execution_worker_stopped")

    async def shutdown(self) -> None:
        for task in list(self._poll_tasks):
            task.cancel()
        if self._poll_tasks:
            await asyncio.gather(*self._poll_tasks, return_exceptions=True)

    # ----------------------------------------------------------------
    # Dispatch
    # ----------------------------------------------------------------

    async def _dispatch(self, decision: RiskDecision) -> None:
        if decision.status == RiskStatus.RISK_REJECTED:
            # Should never arrive here per channel contract (risk_engine publishes
            # rejections to sg:risk_rejected:{symbol}), but defend against it anyway.
            log.warning("unexpected_rejected_decision_on_approved_channel", intent_id=str(decision.intent_id))
            return

        if decision.kill_switch_active:
            log.warning(
                "kill_switch_active_skipping_intent", intent_id=str(decision.intent_id), symbol=decision.symbol
            )
            return

        if decision.status == RiskStatus.RISK_HOLD:
            await self._handle_hold(decision)
            return

        await self._handle_approved(decision)

    # ----------------------------------------------------------------
    # RISK_HOLD
    # ----------------------------------------------------------------

    async def _handle_hold(self, decision: RiskDecision) -> None:
        idempotency_key = util.make_idempotency_key(decision.intent_id)
        order_id = uuid.uuid4()

        if not await db.claim_idempotency_key(idempotency_key, order_id):
            log.info("duplicate_hold_intent_ignored", intent_id=str(decision.intent_id))
            return

        order = Order(
            order_id=order_id,
            intent_id=decision.intent_id,
            correlation_id=decision.correlation_id,
            symbol=decision.symbol,
            action=decision.action,
            state=OrderState.HELD,
            approved_allocation_inr=decision.approved_allocation_inr,
            execution_style=ExecutionStyle.AGGRESSIVE,  # not meaningful until/unless promoted
            risk_band=decision.risk_band,
            market_regime=decision.market_regime,
            idempotency_key=idempotency_key,
        )
        await db.insert_order(order, reason="risk_hold_received")
        await hold_manager.park_held_intent(decision, order)

    # ----------------------------------------------------------------
    # RISK_APPROVED
    # ----------------------------------------------------------------

    async def _handle_approved(self, decision: RiskDecision) -> None:
        idempotency_key = util.make_idempotency_key(decision.intent_id)
        order_id = uuid.uuid4()

        if not await db.claim_idempotency_key(idempotency_key, order_id):
            existing_order_id = await db.get_order_id_for_idempotency_key(idempotency_key)
            log.info(
                "duplicate_approved_intent_ignored",
                intent_id=str(decision.intent_id),
                existing_order_id=str(existing_order_id),
            )
            return

        order = Order(
            order_id=order_id,
            intent_id=decision.intent_id,
            correlation_id=decision.correlation_id,
            symbol=decision.symbol,
            action=decision.action,
            state=OrderState.PENDING,
            approved_allocation_inr=decision.approved_allocation_inr,
            execution_style=ExecutionStyle.AGGRESSIVE,  # overwritten once routed
            risk_band=decision.risk_band,
            market_regime=decision.market_regime,
            idempotency_key=idempotency_key,
        )
        await db.insert_order(order, reason="risk_approved_received")

        await self._route_and_submit(order, decision)

    async def _route_and_submit(self, order: Order, decision: RiskDecision) -> None:
        order = await db.update_order_state(order.order_id, OrderState.PENDING, OrderState.ROUTING, reason="routing")

        reference_price = await self.market_data_client.get_last_price(decision.symbol)
        if reference_price is None:
            await self._fail_order(order, "no_reference_price_available")
            return

        try:
            routing_decision = route(decision, reference_price)
        except RoutingError as exc:
            await self._fail_order(order, str(exc))
            return

        order = await self._persist_routing_fields(order, routing_decision)
        await self._submit_to_broker(order)

    async def _persist_routing_fields(self, order: Order, routing_decision: RoutingDecision) -> Order:
        """Persist sizing/order-type decisions made by the router. This does not
        change `state`, so it bypasses the state-machine-guarded update_order_state
        helper (which requires a from_state -> to_state transition) and writes
        directly. Always called while the order is in ROUTING."""
        async with db.pool.acquire() as conn:
            row = await conn.fetchrow(
                """UPDATE exec_orders SET
                       quantity = $1, order_type = $2, limit_price = $3, validity = $4,
                       execution_style = $5, intended_price_inr = $6, updated_at = now()
                   WHERE order_id = $7
                   RETURNING *""",
                routing_decision.quantity,
                routing_decision.order_type.value,
                routing_decision.limit_price,
                routing_decision.validity.value,
                routing_decision.execution_style.value,
                routing_decision.intended_price_inr,
                order.order_id,
            )
        return db._row_to_order(row)

    async def _persist_broker_order_id(self, order: Order, broker_order_id: str | None) -> Order:
        async with db.pool.acquire() as conn:
            row = await conn.fetchrow(
                "UPDATE exec_orders SET broker_order_id = $1, updated_at = now() WHERE order_id = $2 RETURNING *",
                broker_order_id,
                order.order_id,
            )
        return db._row_to_order(row)

    async def _submit_to_broker(self, order: Order) -> None:
        request = BrokerOrderRequest(
            order=order,
            order_type=order.order_type,
            quantity=order.quantity,
            limit_price=order.limit_price,
            validity=order.validity.value,
            idempotency_key=order.idempotency_key,
        )

        order = await db.update_order_state(
            order.order_id, OrderState.ROUTING, OrderState.SUBMITTED, reason="submitting_to_broker"
        )

        try:
            response = await self.broker_client.place_order(request)
        except BrokerOrderRejected as exc:
            await db.update_order_state(
                order.order_id, OrderState.SUBMITTED, OrderState.REJECTED,
                reason="broker_rejected", last_error=str(exc.reason),
            )
            orders_terminal_total.labels(state=OrderState.REJECTED.value).inc()
            await event_bus.publish(self._terminal_event(order, OrderState.REJECTED, str(exc.reason)))
            return
        except BrokerServiceError as exc:
            broker_call_failures_total.labels(operation="place_order").inc()
            await self._fail_order(order, f"broker_service_error: {exc}", from_state=OrderState.SUBMITTED)
            return
        except Exception as exc:
            broker_call_failures_total.labels(operation="place_order").inc()
            log.exception("unexpected_broker_submit_error", order_id=str(order.order_id))
            await self._fail_order(order, f"unexpected_error: {exc}", from_state=OrderState.SUBMITTED)
            return

        broker_order_id = response.get("broker_order_id") or response.get("order_id")
        order = await self._persist_broker_order_id(order, broker_order_id)

        orders_placed_total.labels(symbol=order.symbol, order_type=order.order_type.value).inc()
        await event_bus.publish(
            ExecutionEvent(
                event_type="ORDER_SUBMITTED",
                order_id=order.order_id,
                intent_id=order.intent_id,
                correlation_id=order.correlation_id,
                symbol=order.symbol,
                action=order.action,
                state=order.state,
                quantity=order.quantity,
                broker_order_id=order.broker_order_id,
            )
        )

        self._spawn_post_submit_poller(order)

    def _spawn_post_submit_poller(self, order: Order) -> None:
        task = asyncio.create_task(self._post_submit_poll(order))
        self._poll_tasks.add(task)
        task.add_done_callback(self._poll_tasks.discard)

    async def _post_submit_poll(self, order: Order) -> None:
        """Poll broker_service shortly after submission until terminal or timeout.
        reconciliation_loop is the safety net if this task is lost (process
        restart) or the order outlives the poll window (e.g. a resting limit order)."""
        elapsed = 0.0
        while elapsed < settings.post_submit_poll_timeout_seconds:
            await asyncio.sleep(settings.post_submit_poll_interval_seconds)
            elapsed += settings.post_submit_poll_interval_seconds

            current = await db.get_order(order.order_id)
            if current is None or state_machine.is_terminal(current.state):
                return
            if not current.broker_order_id:
                continue

            try:
                payload = await self.broker_client.get_order_status(current.broker_order_id)
            except BrokerServiceError:
                continue
            except Exception:
                log.exception("post_submit_poll_error", order_id=str(order.order_id))
                continue

            try:
                current = await apply_broker_status(current, payload, source="post_submit_poll")
            except Exception:
                log.exception("post_submit_poll_apply_status_failed", order_id=str(order.order_id))
                continue
            if state_machine.is_terminal(current.state):
                return

        log.debug("post_submit_poll_timed_out_handing_to_reconciliation", order_id=str(order.order_id))

    # ----------------------------------------------------------------
    # Shared failure handling
    # ----------------------------------------------------------------

    async def _fail_order(self, order: Order, reason: str, from_state: OrderState | None = None) -> None:
        """On the first failure, attempt one application-level retry (fresh
        reference price + re-route + re-submit). Network-level transient
        failures are already retried inside BrokerServiceClient via tenacity,
        so this covers things like a stale/missing reference price or a
        broker_service hiccup that outlasted those retries. Anything beyond
        that is marked FAILED for a human or the alerting path to handle."""
        from_state = from_state or order.state

        if order.retry_count < MAX_APPLICATION_LEVEL_RETRIES:
            order_retry_total.labels(symbol=order.symbol).inc()
            log.warning(
                "order_application_retry", order_id=str(order.order_id), reason=reason,
                retry_count=order.retry_count + 1,
            )
            try:
                retried = await db.update_order_state(
                    order.order_id, from_state, OrderState.ROUTING,
                    reason="application_level_retry", retry_count=order.retry_count + 1, last_error=reason,
                )
            except db.StaleOrderStateError:
                log.warning("retry_skipped_state_already_advanced", order_id=str(order.order_id))
                return

            reference_price = await self.market_data_client.get_last_price(retried.symbol)
            if reference_price is not None:
                try:
                    routing_decision = RoutingDecision(
                        execution_style=ExecutionStyle(retried.execution_style)
                        if retried.execution_style else ExecutionStyle.AGGRESSIVE,
                        order_type=retried.order_type,
                        quantity=retried.quantity or 0,
                        limit_price=retried.limit_price,
                        validity=retried.validity,
                        intended_price_inr=reference_price,
                    )
                    if routing_decision.quantity > 0:
                        retried = await self._persist_routing_fields(retried, routing_decision)
                        await self._submit_to_broker(retried)
                        return
                except Exception:
                    log.exception("application_level_retry_resubmit_failed", order_id=str(order.order_id))
            # Fall through to FAILED if we couldn't get a usable price/quantity.
            order = retried

        try:
            await db.update_order_state(
                order.order_id, order.state, OrderState.FAILED,
                reason=reason, last_error=reason, retry_count=order.retry_count + 1,
            )
        except db.StaleOrderStateError:
            log.warning("fail_order_state_already_advanced", order_id=str(order.order_id))
            return

        orders_terminal_total.labels(state=OrderState.FAILED.value).inc()
        await event_bus.publish(self._terminal_event(order, OrderState.FAILED, reason))

    def _terminal_event(self, order: Order, state: OrderState, reason: str) -> ExecutionEvent:
        return ExecutionEvent(
            event_type=f"ORDER_{state.value}",
            order_id=order.order_id,
            intent_id=order.intent_id,
            correlation_id=order.correlation_id,
            symbol=order.symbol,
            action=order.action,
            state=state,
            reason=reason,
        )
