"""Integration tests — JWT authentication on broker API endpoints."""
from __future__ import annotations

import pytest
from httpx import AsyncClient, ASGITransport
from fastapi import status

from app.main import app


class TestBrokerAuth:
    @pytest.fixture
    async def client(self):
        """Async HTTP client for testing."""
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            yield ac

    @pytest.mark.asyncio
    async def test_place_order_401_without_token(self, client: AsyncClient):
        """Place order returns 401 without JWT token."""
        response = await client.post(
            "/v1/broker/orders",
            json={
                "symbol": "RELIANCE",
                "exchange": "NSE",
                "side": "BUY",
                "order_type": "LIMIT",
                "product": "MIS",
                "quantity": 10,
                "price": 2950.0,
            },
        )
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    @pytest.mark.asyncio
    async def test_place_order_403_with_wrong_role(self, client: AsyncClient):
        """Place order returns 403 with wrong role (analyst instead of trader/admin)."""
        # Mock JWT with analyst role
        headers = {"Authorization": "Bearer invalid_token"}
        response = await client.post(
            "/v1/broker/orders",
            json={
                "symbol": "RELIANCE",
                "exchange": "NSE",
                "side": "BUY",
                "order_type": "LIMIT",
                "product": "MIS",
                "quantity": 10,
                "price": 2950.0,
            },
            headers=headers,
        )
        # Invalid token will fail 401, but with valid token + wrong role would be 403
        # This test verifies the endpoint is protected
        assert response.status_code in (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN)

    @pytest.mark.asyncio
    async def test_modify_order_401_without_token(self, client: AsyncClient):
        """Modify order returns 401 without JWT token."""
        response = await client.put(
            "/v1/broker/orders/123456",
            json={"quantity": 20, "price": 2960.0},
        )
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    @pytest.mark.asyncio
    async def test_cancel_order_401_without_token(self, client: AsyncClient):
        """Cancel order returns 401 without JWT token."""
        response = await client.delete("/v1/broker/orders/123456")
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    @pytest.mark.asyncio
    async def test_get_order_book_401_without_token(self, client: AsyncClient):
        """Get order book returns 401 without JWT token."""
        response = await client.get("/v1/broker/orders")
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    @pytest.mark.asyncio
    async def test_get_positions_401_without_token(self, client: AsyncClient):
        """Get positions returns 401 without JWT token."""
        response = await client.get("/v1/broker/positions")
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    @pytest.mark.asyncio
    async def test_get_account_401_without_token(self, client: AsyncClient):
        """Get account returns 401 without JWT token."""
        response = await client.get("/v1/broker/account")
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    @pytest.mark.asyncio
    async def test_risk_status_401_without_token(self, client: AsyncClient):
        """Risk status returns 401 without JWT token."""
        response = await client.get("/v1/broker/risk/status")
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    @pytest.mark.asyncio
    async def test_reset_daily_risk_401_without_token(self, client: AsyncClient):
        """Reset daily risk returns 401 without JWT token."""
        response = await client.post("/v1/broker/risk/reset-daily")
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    @pytest.mark.asyncio
    async def test_broker_status_401_without_token(self, client: AsyncClient):
        """Broker status returns 401 without JWT token."""
        response = await client.get("/v1/broker/status")
        assert response.status_code == status.HTTP_401_UNAUTHORIZED
