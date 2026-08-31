"""Integration tests — JWT authentication on market data API endpoints."""
from __future__ import annotations

import pytest
from httpx import AsyncClient, ASGITransport
from fastapi import status

from app.main import app


class TestMarketDataAuth:
    @pytest.fixture
    async def client(self):
        """Async HTTP client for testing."""
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            yield ac

    @pytest.mark.asyncio
    async def test_get_quote_401_without_token(self, client: AsyncClient):
        """Get quote returns 401 without JWT token."""
        response = await client.get("/v1/market/quote/RELIANCE")
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    @pytest.mark.asyncio
    async def test_get_quotes_401_without_token(self, client: AsyncClient):
        """Get quotes returns 401 without JWT token."""
        response = await client.post("/v1/market/quotes", json=["RELIANCE", "TCS"])
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    @pytest.mark.asyncio
    async def test_get_bars_401_without_token(self, client: AsyncClient):
        """Get bars returns 401 without JWT token."""
        from datetime import date
        response = await client.get(
            "/v1/market/bars/RELIANCE",
            params={"timeframe": "1m", "from_date": "2024-01-01", "to_date": "2024-01-02"},
        )
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    @pytest.mark.asyncio
    async def test_subscribe_401_without_token(self, client: AsyncClient):
        """Subscribe returns 401 without JWT token."""
        response = await client.post("/v1/market/subscribe", json={"symbols": ["RELIANCE"]})
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    @pytest.mark.asyncio
    async def test_unsubscribe_401_without_token(self, client: AsyncClient):
        """Unsubscribe returns 401 without JWT token."""
        response = await client.post("/v1/market/unsubscribe", json={"symbols": ["RELIANCE"]})
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    @pytest.mark.asyncio
    async def test_backfill_401_without_token(self, client: AsyncClient):
        """Backfill returns 401 without JWT token."""
        from datetime import date
        response = await client.post(
            "/v1/market/backfill",
            json={
                "symbol": "RELIANCE",
                "timeframe": "1m",
                "from_date": "2024-01-01",
                "to_date": "2024-01-02",
            },
        )
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    @pytest.mark.asyncio
    async def test_search_instruments_401_without_token(self, client: AsyncClient):
        """Search instruments returns 401 without JWT token."""
        response = await client.get("/v1/market/instruments/search", params={"q": "RELIANCE"})
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    @pytest.mark.asyncio
    async def test_get_instrument_401_without_token(self, client: AsyncClient):
        """Get instrument returns 401 without JWT token."""
        response = await client.get("/v1/market/instruments/RELIANCE")
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    @pytest.mark.asyncio
    async def test_feed_status_401_without_token(self, client: AsyncClient):
        """Feed status returns 401 without JWT token."""
        response = await client.get("/v1/market/status")
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    @pytest.mark.asyncio
    async def test_market_status_401_without_token(self, client: AsyncClient):
        """Market status returns 401 without JWT token."""
        response = await client.get("/v1/market/market-status")
        assert response.status_code == status.HTTP_401_UNAUTHORIZED
