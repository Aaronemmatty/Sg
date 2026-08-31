from __future__ import annotations

from app.clients.base_client import BaseServiceClient
from app.core.config import settings


class RiskClient(BaseServiceClient):
    """Client for risk_engine_service (8007).

    UNCONFIRMED CONTRACT — the platform handover documents 8007's
    capabilities (VaR, drawdown, exposure, correlation, volatility, margin,
    kill switch, circuit breakers, scoring) and its Redis channels, but does
    not document a REST API. The endpoints below are a reasonable
    assumption following the same `/api/v1/...` convention as
    portfolio_management_service — confirm against the real 8007 router
    before relying on this in production. Isolated entirely to this file so
    a contract correction only touches one place.
    """

    service_label = "risk_engine_service"

    def __init__(self) -> None:
        super().__init__(settings.risk_engine_service_url, settings.http_client_timeout_seconds)

    async def get_risk_snapshot(self) -> dict:
        """Assumed: GET /api/v1/risk/snapshot →
        {var_inr, max_drawdown_pct, exposure_pct, correlation_matrix,
         volatility, margin_used_pct, kill_switch_active, circuit_breakers: [...]}
        """
        return await self._get("/api/v1/risk/snapshot")

    async def get_symbol_risk(self, symbol: str) -> dict:
        """Assumed: GET /api/v1/risk/snapshot/{symbol}"""
        return await self._get(f"/api/v1/risk/snapshot/{symbol}")

    async def get_recent_risk_events(self, limit: int = 20) -> dict:
        """Assumed: GET /api/v1/risk/events/recent?limit=N — recent
        RISK_APPROVED / RISK_REJECTED / RISK_HOLD / kill-switch events."""
        return await self._get("/api/v1/risk/events/recent", params={"limit": limit})
