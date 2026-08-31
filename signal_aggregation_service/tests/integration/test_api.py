from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_engine, get_redis, get_weight_store
from app.core.security import verify_token
from app.db.session import get_session
from app.main import app
from app.models.domain import AggregatedSignalResult, SignalAction


@pytest.fixture
def fake_result() -> AggregatedSignalResult:
    return AggregatedSignalResult(
        symbol="AAPL",
        timeframe="5m",
        final_signal=SignalAction.BUY,
        confidence=0.84,
        contributors=["trend_following", "breakout", "ml_prediction"],
        regime="TRENDING",
        net_score=0.42,
        agreement_ratio=0.9,
        votes={},
        timestamp=datetime.now(timezone.utc),
        weights_version="static_v1+db_overrides",
    )


@pytest.fixture
def client(fake_result, monkeypatch):
    monkeypatch.setattr("app.services.redis_client.AggregationRedisClient.connect", AsyncMock())
    monkeypatch.setattr("app.services.redis_client.AggregationRedisClient.close", AsyncMock())
    monkeypatch.setattr("app.services.signal_consumer.SignalConsumer.start", AsyncMock())
    monkeypatch.setattr("app.services.signal_consumer.SignalConsumer.stop", AsyncMock())
    monkeypatch.setattr("app.workers.scheduler.AggregationWatchdogScheduler.start", AsyncMock())
    monkeypatch.setattr("app.workers.scheduler.AggregationWatchdogScheduler.stop", AsyncMock())
    monkeypatch.setattr(
        "app.services.weights_cache_invalidator.WeightsCacheInvalidator.start", AsyncMock()
    )
    monkeypatch.setattr(
        "app.services.weights_cache_invalidator.WeightsCacheInvalidator.stop", AsyncMock()
    )
    monkeypatch.setattr("app.db.session.engine.dispose", AsyncMock())

    mock_redis = MagicMock()
    mock_redis.get_cached_result = AsyncMock(return_value=fake_result)
    mock_redis.publish_weights_updated = AsyncMock()

    mock_engine = MagicMock()
    mock_engine.aggregate = AsyncMock(return_value=fake_result)

    mock_weight_store = MagicMock()
    mock_weight_store.get_all_for_regime = AsyncMock(return_value={})
    mock_weight_store.upsert = AsyncMock(return_value={"trend_following": 0.5})

    async def fake_session():
        yield MagicMock()

    app.dependency_overrides[get_redis] = lambda: mock_redis
    app.dependency_overrides[get_engine] = lambda: mock_engine
    app.dependency_overrides[get_weight_store] = lambda: mock_weight_store
    app.dependency_overrides[get_session] = fake_session
    app.dependency_overrides[verify_token] = lambda: {"sub": "test-user"}

    with TestClient(app) as test_client:
        yield test_client

    app.dependency_overrides.clear()


def test_health_endpoint(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["service"] == "signal_aggregation_service"


def test_get_signal_returns_cached_result(client):
    resp = client.get("/api/v1/signal/AAPL")
    assert resp.status_code == 200
    body = resp.json()
    assert body["final_signal"] == "BUY"
    assert body["symbol"] == "AAPL"
    assert body["confidence"] == pytest.approx(0.84)


def test_get_signal_contract_shape_matches_brief_example(client):
    resp = client.get("/api/v1/signal/AAPL/contract")
    assert resp.status_code == 200
    body = resp.json()
    assert set(body.keys()) == {"symbol", "final_signal", "confidence", "contributors"}
    assert body["symbol"] == "AAPL"
    assert body["final_signal"] == "BUY"
    assert body["contributors"] == ["trend_following", "breakout", "ml_prediction"]


def test_recalculate_endpoint(client):
    resp = client.post("/api/v1/signal/recalculate", json={"symbol": "AAPL", "timeframe": "5m"})
    assert resp.status_code == 202
    assert resp.json()["triggered"] == ["AAPL"]


def test_get_weights_endpoint_returns_static_defaults_when_no_overrides(client):
    resp = client.get("/api/v1/weights/TRENDING")
    assert resp.status_code == 200
    body = resp.json()
    assert body["regime"] == "TRENDING"
    assert body["effective_weights"]["trend_following"] == pytest.approx(0.40)
    assert body["source"] == "static_default"


def test_put_weights_endpoint_updates_and_publishes_invalidation(client):
    resp = client.put("/api/v1/weights/TRENDING", json={"regime": "TRENDING", "weights": {"trend_following": 0.5}})
    assert resp.status_code == 200
    body = resp.json()
    assert body["source"] == "merged"


def test_put_weights_rejects_negative_weights(client):
    resp = client.put("/api/v1/weights/TRENDING", json={"regime": "TRENDING", "weights": {"trend_following": -0.1}})
    assert resp.status_code == 400


def test_metrics_endpoint(client):
    resp = client.get("/metrics")
    assert resp.status_code == 200
