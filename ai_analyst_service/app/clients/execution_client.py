from __future__ import annotations

from app.clients.base_client import BaseServiceClient
from app.core.config import settings


class ExecutionClient(BaseServiceClient):
    """Client for execution_engine_service (8008).

    UNCONFIRMED CONTRACT — the platform handover documents 8008's
    ExecutionEvent output contract (consumed by 8009 over Redis) and its
    general capabilities (order routing, smart execution, slippage
    tracking, retries, reconciliation), but not a REST API. The endpoints
    below are a reasonable assumption following the same `/api/v1/...`
    convention as the rest of the platform — confirm against the real 8008
    router before relying on this in production. Isolated entirely to this
    file so a contract correction only touches one place.
    """

    service_label = "execution_engine_service"

    def __init__(self) -> None:
        super().__init__(settings.execution_engine_service_url, settings.http_client_timeout_seconds)

    async def get_order(self, order_id: str) -> dict:
        """Assumed: GET /api/v1/orders/{order_id} → ExecutionEvent-shaped record
        plus routing/reconciliation metadata."""
        return await self._get(f"/api/v1/orders/{order_id}")

    async def get_recent_orders(self, symbol: str | None = None, days: int = 7, limit: int = 50) -> dict:
        """Assumed: GET /api/v1/orders/recent?symbol=&days=&limit="""
        params: dict = {"days": days, "limit": limit}
        if symbol:
            params["symbol"] = symbol
        return await self._get("/api/v1/orders/recent", params=params)
