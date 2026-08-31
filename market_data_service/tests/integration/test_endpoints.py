"""Integration tests — market data API endpoints."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

pytestmark = pytest.mark.asyncio


@pytest.fixture
async def client():
    """TestClient with engine mocked out (no real Kite/Redis needed)."""
    # Patch engine singleton before app import
    mock_engine = MagicMock()
    mock_engine.is_running = True
    mock_engine.subscribed_count = 5
    mock_engine.get_stats.return_value = {
        "running": True,
        "mode": "mock",
        "subscribed_symbols": 5,
        "feed": {"ticks_received": 1000},
        "aggregator": {"active_candles": 50, "active_symbols": 5},
        "writer": {"buffer_depth": 0},
    }
    mock_engine.subscribe = AsyncMock(return_value={"NSE:RELIANCE": 738561})
    mock_engine.unsubscribe = AsyncMock()

    with patch("app.services.engine._engine", mock_engine), \
         patch("app.core.redis.get_redis", AsyncMock(return_value=AsyncMock(ping=AsyncMock()))), \
         patch("app.services.engine.init_engine", return_value=mock_engine), \
         patch("app.services.engine.get_engine", return_value=mock_engine):

        from app.main import app
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as c:
            yield c


class TestHealthEndpoints:
    async def test_health(self, client: AsyncClient):
        resp = await client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["service"] == "market-data"

    async def test_market_status(self, client: AsyncClient):
        resp = await client.get("/v1/market/market-status")
        assert resp.status_code == 200
        data = resp.json()
        assert "is_open" in data
        assert "message" in data
        assert isinstance(data["is_open"], bool)


class TestQuoteEndpoints:
    async def test_quote_not_found(self, client: AsyncClient):
        with patch("app.api.v1.endpoints.market.get_cached_tick", AsyncMock(return_value=None)):
            resp = await client.get("/v1/market/quote/NSE:GHOST")
        assert resp.status_code == 404

    async def test_quote_found(self, client: AsyncClient):
        mock_tick = {
            "symbol": "NSE:RELIANCE",
            "exchange": "NSE",
            "last_price": 2950.0,
            "volume": 1234567,
            "timestamp_ns": 1700000000000000000,
            "open": 2940.0,
            "high": 2960.0,
            "low": 2935.0,
            "bid": 2949.0,
            "ask": 2951.0,
        }
        with patch("app.api.v1.endpoints.market.get_cached_tick", AsyncMock(return_value=mock_tick)):
            resp = await client.get("/v1/market/quote/NSE:RELIANCE")
        assert resp.status_code == 200
        data = resp.json()
        assert data["symbol"] == "NSE:RELIANCE"
        assert data["last_price"] == 2950.0


class TestSubscriptionEndpoints:
    async def test_subscribe(self, client: AsyncClient):
        with patch("app.api.v1.endpoints.market.get_engine") as mock_get_eng:
            mock_e = AsyncMock()
            mock_e.subscribe = AsyncMock(return_value={"NSE:RELIANCE": 738561})
            mock_get_eng.return_value = mock_e

            resp = await client.post("/v1/market/subscribe", json={"symbols": ["NSE:RELIANCE"]})

        assert resp.status_code == 200
        data = resp.json()
        assert "subscribed" in data
        assert data["total"] == 1

    async def test_unsubscribe(self, client: AsyncClient):
        with patch("app.api.v1.endpoints.market.get_engine") as mock_get_eng:
            mock_e = AsyncMock()
            mock_e.unsubscribe = AsyncMock()
            mock_get_eng.return_value = mock_e

            resp = await client.post("/v1/market/unsubscribe", json={"symbols": ["NSE:RELIANCE"]})
        assert resp.status_code == 204


class TestInstrumentEndpoints:
    async def test_search_no_results(self, client: AsyncClient):
        with patch("app.api.v1.endpoints.market.get_registry") as mock_reg:
            mock_reg.return_value.search.return_value = []
            resp = await client.get("/v1/market/instruments/search?q=ZZZZZ")
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 0
        assert data["results"] == []

    async def test_instrument_not_found(self, client: AsyncClient):
        with patch("app.api.v1.endpoints.market.get_registry") as mock_reg:
            mock_reg.return_value.get_by_symbol.return_value = None
            resp = await client.get("/v1/market/instruments/NSE:GHOST")
        assert resp.status_code == 404


class TestStatusEndpoint:
    async def test_feed_status(self, client: AsyncClient):
        with patch("app.api.v1.endpoints.market.get_engine") as mock_get_eng, \
             patch("app.api.v1.endpoints.market.get_feed_status",
                   AsyncMock(return_value={"status": "connected"})):
            mock_e = MagicMock()
            mock_e.subscribed_count = 10
            mock_e.get_stats.return_value = {"aggregator": {}, "writer": {}, "feed": {}}
            mock_get_eng.return_value = mock_e

            resp = await client.get("/v1/market/status")
        assert resp.status_code == 200
        data = resp.json()
        assert "status" in data
        assert "market_open" in data
