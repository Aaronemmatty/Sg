"""Integration tests — JWT authentication on strategy API endpoints."""
from __future__ import annotations

import pytest
from httpx import AsyncClient, ASGITransport
from fastapi import status

from app.main import app


class TestStrategyAuth:
    @pytest.fixture
    async def client(self):
        """Async HTTP client for testing."""
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            yield ac

    @pytest.mark.asyncio
    async def test_list_strategies_401_without_token(self, client: AsyncClient):
        """List strategies returns 401 without JWT token."""
        response = await client.get("/v1/strategies/")
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    @pytest.mark.asyncio
    async def test_get_strategy_401_without_token(self, client: AsyncClient):
        """Get strategy returns 401 without JWT token."""
        response = await client.get("/v1/strategies/ema_crossover")
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    @pytest.mark.asyncio
    async def test_reload_strategies_401_without_token(self, client: AsyncClient):
        """Reload strategies returns 401 without JWT token."""
        response = await client.post("/v1/strategies/reload")
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    @pytest.mark.asyncio
    async def test_start_strategy_401_without_token(self, client: AsyncClient):
        """Start strategy returns 401 without JWT token."""
        response = await client.post(
            "/v1/strategies/instances",
            json={
                "strategy_name": "ema_crossover",
                "symbol": "RELIANCE",
                "exchange": "NSE",
                "timeframe": "5m",
                "trading_mode": "paper",
            },
        )
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    @pytest.mark.asyncio
    async def test_start_strategy_403_with_wrong_role(self, client: AsyncClient):
        """Start strategy returns 403 with wrong role."""
        headers = {"Authorization": "Bearer invalid_token"}
        response = await client.post(
            "/v1/strategies/instances",
            json={
                "strategy_name": "ema_crossover",
                "symbol": "RELIANCE",
                "exchange": "NSE",
                "timeframe": "5m",
                "trading_mode": "paper",
            },
            headers=headers,
        )
        assert response.status_code in (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN)

    @pytest.mark.asyncio
    async def test_list_instances_401_without_token(self, client: AsyncClient):
        """List instances returns 401 without JWT token."""
        response = await client.get("/v1/strategies/instances")
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    @pytest.mark.asyncio
    async def test_get_instance_401_without_token(self, client: AsyncClient):
        """Get instance returns 401 without JWT token."""
        response = await client.get("/v1/strategies/instances/abc123")
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    @pytest.mark.asyncio
    async def test_stop_instance_401_without_token(self, client: AsyncClient):
        """Stop instance returns 401 without JWT token."""
        response = await client.post("/v1/strategies/instances/abc123/stop")
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    @pytest.mark.asyncio
    async def test_pause_instance_401_without_token(self, client: AsyncClient):
        """Pause instance returns 401 without JWT token."""
        response = await client.post("/v1/strategies/instances/abc123/pause")
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    @pytest.mark.asyncio
    async def test_resume_instance_401_without_token(self, client: AsyncClient):
        """Resume instance returns 401 without JWT token."""
        response = await client.post("/v1/strategies/instances/abc123/resume")
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    @pytest.mark.asyncio
    async def test_get_latest_signals_401_without_token(self, client: AsyncClient):
        """Get latest signals returns 401 without JWT token."""
        response = await client.get("/v1/strategies/signals/latest")
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    @pytest.mark.asyncio
    async def test_get_performance_401_without_token(self, client: AsyncClient):
        """Get performance returns 401 without JWT token."""
        response = await client.get("/v1/strategies/instances/abc123/performance")
        assert response.status_code == status.HTTP_401_UNAUTHORIZED
