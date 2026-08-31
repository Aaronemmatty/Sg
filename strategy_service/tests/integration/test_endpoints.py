"""Integration tests — strategy API endpoints."""
from __future__ import annotations
from unittest.mock import AsyncMock, MagicMock, patch
import pytest
from httpx import ASGITransport, AsyncClient

pytestmark = pytest.mark.asyncio

MOCK_INSTANCE = MagicMock()
MOCK_INSTANCE.to_dict.return_value = {
    "instance_id": "ema_crossover:NSE:RELIANCE:5m",
    "strategy_name": "ema_crossover",
    "version": "1.0.0",
    "symbol": "NSE:RELIANCE",
    "exchange": "NSE",
    "timeframe": "5m",
    "trading_mode": "paper",
    "status": "RUNNING",
    "restart_count": 0,
    "bars_processed": 42,
    "signals_emitted": 7,
    "started_at": "2025-01-01T09:15:00+00:00",
    "stopped_at": None,
    "error": None,
    "params": {"fast_period": 9, "slow_period": 21},
}

MOCK_REG = MagicMock()
MOCK_REG.to_dict.return_value = {
    "name": "ema_crossover", "version": "1.0.0",
    "type": "trend_following", "author": "SG Platform",
    "description": "Dual EMA crossover.", "timeframes": ["5m", "15m"],
    "symbols": ["*"], "min_bars": 50, "parameters": {"fast_period": 9},
    "tags": ["trend"], "is_builtin": True, "file_hash": "abc123",
    "source_path": None, "status": "REGISTERED", "load_error": None,
}


@pytest.fixture
async def client():
    with patch("app.registry.registry._registry") as mock_reg, \
         patch("app.registry.registry._loader") as mock_loader, \
         patch("app.lifecycle.manager._manager") as mock_mgr, \
         patch("app.core.redis._pool", AsyncMock(ping=AsyncMock())), \
         patch("app.registry.registry.get_loader") as mock_get_loader, \
         patch("app.registry.registry.get_registry") as mock_get_reg, \
         patch("app.lifecycle.manager.get_lifecycle_manager") as mock_get_mgr, \
         patch("app.lifecycle.watcher.HotReloadWatcher.start", AsyncMock()), \
         patch("app.lifecycle.watcher.HotReloadWatcher.stop", AsyncMock()), \
         patch("app.registry.registry.StrategyLoader.load_builtins", AsyncMock(return_value=5)), \
         patch("app.registry.registry.StrategyLoader.load_directory", AsyncMock(return_value=0)), \
         patch("app.core.redis.get_redis", AsyncMock(return_value=AsyncMock(ping=AsyncMock(), scan_iter=AsyncMock(return_value=aiter([]))))):

        mock_get_reg.return_value.get_all.return_value = [MOCK_REG]
        mock_get_reg.return_value.get.return_value = MOCK_REG
        mock_get_reg.return_value.count = 1
        mock_get_mgr.return_value.list_instances.return_value = [MOCK_INSTANCE]
        mock_get_mgr.return_value.get_instance.return_value = MOCK_INSTANCE
        mock_get_mgr.return_value.start = AsyncMock(return_value=MOCK_INSTANCE)
        mock_get_mgr.return_value.stop = AsyncMock(return_value=True)
        mock_get_mgr.return_value.pause = AsyncMock(return_value=True)
        mock_get_mgr.return_value.resume = AsyncMock(return_value=True)
        mock_get_mgr.return_value.stop_all = AsyncMock()
        mock_get_loader.return_value.load_builtins = AsyncMock(return_value=5)
        mock_get_loader.return_value.load_directory = AsyncMock(return_value=0)

        from app.main import app
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            yield c


async def aiter(items):
    for item in items:
        yield item


class TestHealthEndpoints:
    async def test_health(self, client: AsyncClient):
        resp = await client.get("/health")
        assert resp.status_code == 200
        assert resp.json()["service"] == "strategy"


class TestStrategyRegistry:
    async def test_list_strategies(self, client: AsyncClient):
        resp = await client.get("/v1/strategies/")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)

    async def test_get_strategy(self, client: AsyncClient):
        resp = await client.get("/v1/strategies/ema_crossover")
        assert resp.status_code == 200
        assert resp.json()["name"] == "ema_crossover"

    async def test_get_nonexistent_strategy(self, client: AsyncClient):
        with patch("app.api.v1.endpoints.strategy.get_registry") as mock:
            mock.return_value.get.return_value = None
            resp = await client.get("/v1/strategies/ghost")
        assert resp.status_code == 404


class TestStrategyInstances:
    async def test_start_strategy(self, client: AsyncClient):
        resp = await client.post("/v1/strategies/instances", json={
            "strategy_name": "ema_crossover",
            "symbol": "NSE:RELIANCE",
            "exchange": "NSE",
            "timeframe": "5m",
            "trading_mode": "paper",
        })
        assert resp.status_code == 201
        assert resp.json()["strategy_name"] == "ema_crossover"

    async def test_list_instances(self, client: AsyncClient):
        resp = await client.get("/v1/strategies/instances")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    async def test_stop_instance(self, client: AsyncClient):
        resp = await client.post("/v1/strategies/instances/ema_crossover:NSE:RELIANCE:5m/stop")
        assert resp.status_code == 200

    async def test_pause_instance(self, client: AsyncClient):
        resp = await client.post("/v1/strategies/instances/ema_crossover:NSE:RELIANCE:5m/pause")
        assert resp.status_code == 200

    async def test_resume_instance(self, client: AsyncClient):
        resp = await client.post("/v1/strategies/instances/ema_crossover:NSE:RELIANCE:5m/resume")
        assert resp.status_code == 200

    async def test_start_invalid_trading_mode(self, client: AsyncClient):
        resp = await client.post("/v1/strategies/instances", json={
            "strategy_name": "ema_crossover",
            "symbol": "NSE:RELIANCE",
            "exchange": "NSE",
            "timeframe": "5m",
            "trading_mode": "invalid_mode",
        })
        assert resp.status_code == 422
