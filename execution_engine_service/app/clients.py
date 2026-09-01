"""
Client for broker_service (8003).

*** CONFIRM BEFORE GOING LIVE ***
The exact REST contract for order placement/status/cancel on broker_service
(8003) is NOT confirmed in the handover spec (same caveat the risk_engine
team flagged for /margins and /portfolio/snapshot). The shapes below are
the assumed v1 contract. If they differ, only this file needs to change —
that isolation is intentional (same pattern as risk_engine's clients.py).

Assumed endpoints:
  POST   /orders                  -> place order   (idempotent via header)
  GET    /orders/{broker_order_id} -> order status
  POST   /orders/{broker_order_id}/cancel -> cancel order
"""
from __future__ import annotations

import uuid
from typing import Any

import httpx
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from app.config import settings
from app.logging_config import get_logger
from app.models import Order, OrderType

log = get_logger(__name__)


class BrokerServiceError(Exception):
    """Raised on a definitive broker-side error (not a transient network failure)."""


class BrokerOrderRejected(BrokerServiceError):
    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(f"Broker rejected order: {reason}")


class BrokerOrderRequest:
    """Internal representation of the outbound order request, built by the router."""

    def __init__(
        self,
        order: Order,
        order_type: OrderType,
        quantity: int,
        limit_price: float | None,
        validity: str,
        idempotency_key: str,
        product: str = "MIS",
    ):
        self.order = order
        self.order_type = order_type
        self.quantity = quantity
        self.limit_price = limit_price
        self.validity = validity
        self.idempotency_key = idempotency_key
        self.product = product or getattr(order, "product", "MIS") or "MIS"

    def to_payload(self) -> dict[str, Any]:
        return {
            "intent_id": str(self.order.intent_id),
            "correlation_id": str(self.order.correlation_id),
            "symbol": self.order.symbol,
            "action": self.order.action.value,
            "order_type": self.order_type.value,
            "product": self.product,
            "quantity": self.quantity,
            "limit_price": self.limit_price,
            "validity": self.validity,
        }


_RETRYABLE_EXCEPTIONS = (httpx.ConnectError, httpx.ConnectTimeout, httpx.ReadTimeout, httpx.RemoteProtocolError)


class BrokerServiceClient:
    def __init__(self) -> None:
        self._client = httpx.AsyncClient(
            base_url=settings.broker_service_base_url,
            timeout=settings.broker_service_timeout_seconds,
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    @retry(
        retry=retry_if_exception_type(_RETRYABLE_EXCEPTIONS),
        stop=stop_after_attempt(settings.broker_call_max_retries),
        wait=wait_exponential(multiplier=settings.broker_call_backoff_base_seconds, max=10),
        reraise=True,
    )
    async def place_order(self, request: BrokerOrderRequest) -> dict[str, Any]:
        """Place an order. Idempotency-Key header lets broker_service (if it
        supports it) dedupe a retried request that actually reached it but
        whose response we lost. Network-level failures are retried by tenacity;
        a definitive broker rejection (4xx with a rejection body) is NOT retried
        and surfaces as BrokerOrderRejected."""
        resp = await self._client.post(
            "/orders",
            json=request.to_payload(),
            headers={"Idempotency-Key": request.idempotency_key},
        )
        if resp.status_code == 409:
            # Treat as "already placed" - fetch and return existing state rather than erroring.
            log.warning("broker_idempotent_conflict", idempotency_key=request.idempotency_key)
            existing = resp.json()
            return existing
        if resp.status_code >= 400:
            body = _safe_json(resp)
            reason = body.get("reason", body.get("detail", resp.text)) if isinstance(body, dict) else resp.text
            raise BrokerOrderRejected(reason)
        return resp.json()

    @retry(
        retry=retry_if_exception_type(_RETRYABLE_EXCEPTIONS),
        stop=stop_after_attempt(settings.broker_call_max_retries),
        wait=wait_exponential(multiplier=settings.broker_call_backoff_base_seconds, max=10),
        reraise=True,
    )
    async def get_order_status(self, broker_order_id: str) -> dict[str, Any]:
        resp = await self._client.get(f"/orders/{broker_order_id}")
        if resp.status_code == 404:
            raise BrokerServiceError(f"broker_order_id {broker_order_id} not found")
        resp.raise_for_status()
        return resp.json()

    @retry(
        retry=retry_if_exception_type(_RETRYABLE_EXCEPTIONS),
        stop=stop_after_attempt(settings.broker_call_max_retries),
        wait=wait_exponential(multiplier=settings.broker_call_backoff_base_seconds, max=10),
        reraise=True,
    )
    async def cancel_order(self, broker_order_id: str) -> dict[str, Any]:
        resp = await self._client.post(f"/orders/{broker_order_id}/cancel")
        if resp.status_code >= 400:
            body = _safe_json(resp)
            reason = body.get("reason", resp.text) if isinstance(body, dict) else resp.text
            raise BrokerServiceError(f"cancel failed: {reason}")
        return resp.json()


def _safe_json(resp: httpx.Response) -> Any:
    try:
        return resp.json()
    except Exception:
        return {}


broker_client = BrokerServiceClient()
