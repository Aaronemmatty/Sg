from __future__ import annotations

from app.clients.base_client import BaseServiceClient
from app.core.config import settings


class PortfolioClient(BaseServiceClient):
    """Client for portfolio_management_service (8009).

    Contract is CONFIRMED — this service's full REST API is documented in
    the platform handover, unlike the other clients in this package.
    """

    service_label = "portfolio_management_service"

    def __init__(self) -> None:
        super().__init__(settings.portfolio_management_service_url, settings.http_client_timeout_seconds)

    async def get_snapshot(self) -> dict:
        return await self._get("/api/v1/portfolio/snapshot")

    async def get_positions(self) -> dict:
        return await self._get("/api/v1/portfolio/positions")

    async def get_position(self, symbol: str) -> dict:
        return await self._get(f"/api/v1/portfolio/positions/{symbol}")

    async def get_exposure(self) -> dict:
        return await self._get("/api/v1/portfolio/exposure")

    async def get_performance(self, window: str) -> dict:
        return await self._get(f"/api/v1/performance/{window}")

    async def get_recent_trades(self, limit: int = 50) -> dict:
        return await self._get("/api/v1/ledger/trades", params={"limit": limit})

    async def get_lots(self, symbol: str) -> dict:
        return await self._get(f"/api/v1/portfolio/lots/{symbol}")
