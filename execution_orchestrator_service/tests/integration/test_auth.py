"""Integration tests — JWT authentication on execution orchestrator API endpoints."""
from __future__ import annotations

import pytest
from httpx import AsyncClient, ASGITransport
from fastapi import status

from app.main import app


class TestExecutionOrchestratorAuth:
    @pytest.fixture
    async def client(self):
        """Async HTTP client for testing."""
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            yield ac

    @pytest.mark.asyncio
    async def test_list_intents_401_without_token(self, client: AsyncClient):
        """List intents returns 401 without JWT token."""
        response = await client.get("/api/v1/intents")
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    @pytest.mark.asyncio
    async def test_get_intent_401_without_token(self, client: AsyncClient):
        """Get intent returns 401 without JWT token."""
        response = await client.get("/api/v1/intents/abc123")
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    @pytest.mark.asyncio
    async def test_get_intent_audit_401_without_token(self, client: AsyncClient):
        """Get intent audit returns 401 without JWT token."""
        response = await client.get("/api/v1/intents/abc123/audit")
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    @pytest.mark.asyncio
    async def test_inject_signal_401_without_token(self, client: AsyncClient):
        """Inject signal returns 401 without JWT token."""
        response = await client.post(
            "/api/v1/intents",
            json={
                "symbol": "RELIANCE",
                "timeframe": "5m",
                "action": "BUY",
                "confidence": 0.85,
                "contributors": ["rsi_strategy"],
                "regime": "TRENDING",
                "net_score": 0.75,
                "agreement_ratio": 0.90,
            },
        )
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    @pytest.mark.asyncio
    async def test_inject_signal_403_with_wrong_role(self, client: AsyncClient):
        """Inject signal returns 403 with wrong role."""
        headers = {"Authorization": "Bearer invalid_token"}
        response = await client.post(
            "/api/v1/intents",
            json={
                "symbol": "RELIANCE",
                "timeframe": "5m",
                "action": "BUY",
                "confidence": 0.85,
                "contributors": ["rsi_strategy"],
                "regime": "TRENDING",
                "net_score": 0.75,
                "agreement_ratio": 0.90,
            },
            headers=headers,
        )
        assert response.status_code in (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN)

    @pytest.mark.asyncio
    async def test_get_config_401_without_token(self, client: AsyncClient):
        """Get config returns 401 without JWT token."""
        response = await client.get("/api/v1/config")
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    @pytest.mark.asyncio
    async def test_health_endpoint_open(self, client: AsyncClient):
        """Health endpoint remains open (no auth required)."""
        response = await client.get("/health")
        # Health endpoint should be open for monitoring
        assert response.status_code == status.HTTP_200_OK

    @pytest.mark.asyncio
    async def test_ready_endpoint_open(self, client: AsyncClient):
        """Ready endpoint remains open (no auth required)."""
        response = await client.get("/ready")
        # Ready endpoint should be open for monitoring
        assert response.status_code in (status.HTTP_200_OK, status.HTTP_503_SERVICE_UNAVAILABLE)
