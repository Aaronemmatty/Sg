from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from app.config import Settings
from app.services.redis_client import AggregationRedisClient
from tests.conftest import make_raw_signal


@pytest.fixture
async def fake_redis_client(settings: Settings, monkeypatch):
    import fakeredis.aioredis

    fake_instance = fakeredis.aioredis.FakeRedis(decode_responses=True)

    def fake_from_url(*args, **kwargs):
        return fake_instance

    monkeypatch.setattr("app.services.redis_client.aioredis.from_url", fake_from_url)

    client = AggregationRedisClient(settings)
    await client.connect()
    yield client
    await client.close()


@pytest.mark.asyncio
async def test_get_raw_signal_round_trip(fake_redis_client):
    raw = make_raw_signal("trend_following", symbol="AAPL", timeframe="5m", action="BUY", confidence=0.8)
    await fake_redis_client.client.set("signal:trend_following:AAPL:5m", json.dumps(raw))

    fetched = await fake_redis_client.get_raw_signal("trend_following", "AAPL", "5m")
    assert fetched is not None
    assert fetched["action"] == "BUY"
    assert fetched["confidence"] == 0.8


@pytest.mark.asyncio
async def test_get_raw_signal_returns_none_when_absent(fake_redis_client):
    result = await fake_redis_client.get_raw_signal("nonexistent", "AAPL", "5m")
    assert result is None


@pytest.mark.asyncio
async def test_discover_strategies_finds_custom_strategy_keys(fake_redis_client):
    raw = make_raw_signal("my_custom_alpha", symbol="AAPL", timeframe="5m")
    await fake_redis_client.client.set("signal:my_custom_alpha:AAPL:5m", json.dumps(raw))

    discovered = await fake_redis_client.discover_strategies("AAPL", "5m")
    assert "my_custom_alpha" in discovered


@pytest.mark.asyncio
async def test_collect_all_raw_signals_merges_registry_and_discovered(fake_redis_client, settings):
    # Registry strategy
    raw1 = make_raw_signal("trend_following", symbol="AAPL", timeframe="5m", action="BUY")
    await fake_redis_client.client.set("signal:trend_following:AAPL:5m", json.dumps(raw1))
    # Custom/unregistered strategy
    raw2 = make_raw_signal("genuinely_custom", symbol="AAPL", timeframe="5m", action="SELL")
    await fake_redis_client.client.set("signal:genuinely_custom:AAPL:5m", json.dumps(raw2))

    all_signals = await fake_redis_client.collect_all_raw_signals("AAPL", "5m")
    assert "trend_following" in all_signals
    assert "genuinely_custom" in all_signals


@pytest.mark.asyncio
async def test_get_regime_parses_regime_detection_service_contract(fake_redis_client):
    regime_payload = {
        "regime": "TRENDING",
        "confidence": 0.88,
        "sub_regimes": ["BULLISH", "LOW_VOLATILITY"],
        "symbol": "NIFTY50",
        "timeframe": "5m",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "features": {"adx": 28.4},
    }
    await fake_redis_client.client.set("regime:NIFTY50:5m", json.dumps(regime_payload))

    regime_ref = await fake_redis_client.get_regime("NIFTY50", "5m")
    assert regime_ref is not None
    assert regime_ref.regime == "TRENDING"
    assert regime_ref.confidence == pytest.approx(0.88)


@pytest.mark.asyncio
async def test_get_regime_returns_none_when_absent(fake_redis_client):
    assert await fake_redis_client.get_regime("UNKNOWN_SYMBOL", "5m") is None


@pytest.mark.asyncio
async def test_set_and_get_cached_result_round_trip(fake_redis_client):
    from app.models.domain import AggregatedSignalResult, SignalAction

    result = AggregatedSignalResult(
        symbol="AAPL", timeframe="5m", final_signal=SignalAction.BUY, confidence=0.84,
        contributors=["trend_following"], regime="TRENDING", net_score=0.4, agreement_ratio=0.9,
        votes={}, timestamp=datetime.now(timezone.utc),
    )
    await fake_redis_client.set_cached_result(result)
    fetched = await fake_redis_client.get_cached_result("AAPL", "5m")
    assert fetched is not None
    assert fetched.final_signal == SignalAction.BUY


@pytest.mark.asyncio
async def test_publish_result_reaches_subscriber(fake_redis_client):
    from app.models.domain import AggregatedSignalResult, SignalAction

    pubsub = fake_redis_client.client.pubsub()
    await pubsub.subscribe("sg:aggregated_signal:AAPL")
    await pubsub.get_message(timeout=1)  # drain subscribe confirmation

    result = AggregatedSignalResult(
        symbol="AAPL", timeframe="5m", final_signal=SignalAction.BUY, confidence=0.84,
        contributors=["trend_following"], regime="TRENDING", net_score=0.4, agreement_ratio=0.9,
        votes={}, timestamp=datetime.now(timezone.utc),
    )
    await fake_redis_client.publish_result(result)

    message = await pubsub.get_message(timeout=2)
    assert message is not None
    payload = json.loads(message["data"])
    assert payload["final_signal"] == "BUY"

    await pubsub.unsubscribe()
    await pubsub.aclose()


@pytest.mark.asyncio
async def test_weights_updated_pubsub(fake_redis_client):
    pubsub = await fake_redis_client.subscribe_weights_updated()
    await pubsub.get_message(timeout=1)  # drain subscribe confirmation

    await fake_redis_client.publish_weights_updated("TRENDING")
    message = await pubsub.get_message(timeout=2)
    assert message is not None
    payload = json.loads(message["data"])
    assert payload["regime"] == "TRENDING"

    await pubsub.unsubscribe()
    await pubsub.aclose()
