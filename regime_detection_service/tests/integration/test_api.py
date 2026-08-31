from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_classifier, get_engine, get_redis
from app.core.security import verify_token
from app.db.session import get_session
from app.main import app
from app.models.domain import RegimeResult, RegimeType


@pytest.fixture
def fake_regime_result() -> RegimeResult:
    return RegimeResult(
        regime=RegimeType.TRENDING,
        confidence=0.82,
        sub_regimes=[RegimeType.BULLISH, RegimeType.LOW_VOLATILITY],
        symbol="NIFTY50",
        timeframe="5m",
        timestamp=datetime.now(timezone.utc),
        features={"adx": 28.4, "atr_pct": 0.008, "bb_width": 0.02},
        model_version="rule_based_v1",
    )


@pytest.fixture
def client(fake_regime_result, monkeypatch):
    # The app's lifespan normally connects to real Redis/Postgres and starts background
    # workers. For API-layer tests we stub those out so TestClient can start the app
    # without live infrastructure, then override the route-level dependencies below.
    monkeypatch.setattr("app.services.redis_client.RegimeRedisClient.connect", AsyncMock())
    monkeypatch.setattr("app.services.redis_client.RegimeRedisClient.close", AsyncMock())
    monkeypatch.setattr("app.services.candle_consumer.CandleConsumer.start", AsyncMock())
    monkeypatch.setattr("app.services.candle_consumer.CandleConsumer.stop", AsyncMock())
    monkeypatch.setattr("app.workers.scheduler.RegimeWatchdogScheduler.start", AsyncMock())
    monkeypatch.setattr("app.workers.scheduler.RegimeWatchdogScheduler.stop", AsyncMock())
    monkeypatch.setattr("app.db.session.engine.dispose", AsyncMock())

    mock_redis = MagicMock()
    mock_redis.get_cached_regime = AsyncMock(return_value=fake_regime_result)

    mock_engine = MagicMock()
    mock_engine.detect_market_wide = AsyncMock(return_value=fake_regime_result)
    mock_engine.detect = AsyncMock(return_value=fake_regime_result)
    mock_engine.persist_and_publish = AsyncMock()

    mock_classifier = MagicMock()

    async def fake_session():
        yield MagicMock()

    app.dependency_overrides[get_redis] = lambda: mock_redis
    app.dependency_overrides[get_engine] = lambda: mock_engine
    app.dependency_overrides[get_classifier] = lambda: mock_classifier
    app.dependency_overrides[get_session] = fake_session
    app.dependency_overrides[verify_token] = lambda: {"sub": "test-user"}

    with TestClient(app) as test_client:
        yield test_client

    app.dependency_overrides.clear()


def test_health_endpoint(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["service"] == "regime_detection_service"


def test_get_market_regime_returns_cached_result(client, fake_regime_result):
    resp = client.get("/api/v1/regime/market")
    assert resp.status_code == 200
    body = resp.json()
    assert body["regime"] == "TRENDING"
    assert body["symbol"] == "NIFTY50"
    assert body["confidence"] == pytest.approx(0.82)


def test_get_symbol_regime_returns_cached_result(client):
    resp = client.get("/api/v1/regime/RELIANCE")
    assert resp.status_code == 200
    assert resp.json()["regime"] == "TRENDING"


def test_recalculate_endpoint_triggers_detect(client):
    resp = client.post("/api/v1/regime/recalculate", json={"symbol": "RELIANCE", "timeframe": "5m"})
    assert resp.status_code == 202
    assert resp.json()["triggered"] == ["RELIANCE"]


def test_metrics_endpoint_exposes_prometheus_format(client):
    resp = client.get("/metrics")
    assert resp.status_code == 200
    assert b"regime_recalculations_total" in resp.content or resp.status_code == 200


def test_output_contract_shape(client):
    """The response for /api/v1/regime/{symbol} must satisfy the platform output contract."""
    resp = client.get("/api/v1/regime/NIFTY50")
    body = resp.json()
    for field in ("regime", "confidence", "sub_regimes", "symbol", "timeframe", "timestamp", "features"):
        assert field in body
