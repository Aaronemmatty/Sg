from __future__ import annotations

from app.clients.base_client import BaseServiceClient
from app.core.config import settings


class MarketDataClient(BaseServiceClient):
    """Client for market_data_service (8002).

    UNCONFIRMED CONTRACT — same assumed shape already carried forward from
    portfolio_management_service (8009) and backtesting_engine_service
    (8010): GET /symbols/{symbol}/ltp → {"ltp": float}, and
    GET /symbols/{symbol}/history?days&interval → {"candles": [...]}.
    Isolated entirely to this file.
    """

    service_label = "market_data_service"

    def __init__(self) -> None:
        super().__init__(settings.market_data_service_url, settings.http_client_timeout_seconds)

    async def get_ltp(self, symbol: str) -> dict:
        return await self._get(f"/symbols/{symbol}/ltp")

    async def get_recent_history(self, symbol: str, days: int = 5, interval: str = "1d") -> dict:
        return await self._get(
            f"/symbols/{symbol}/history", params={"days": days, "interval": interval}
        )
