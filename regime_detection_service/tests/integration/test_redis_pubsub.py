from __future__ import annotations

import json

import pytest

from app.config import Settings
from app.services.redis_client import RegimeRedisClient


@pytest.fixture
async def fake_redis_client(settings: Settings, monkeypatch):
    """RegimeRedisClient backed by an in-memory fakeredis instance instead of real Redis."""
    import fakeredis.aioredis

    fake_instance = fakeredis.aioredis.FakeRedis(decode_responses=True)

    def fake_from_url(*args, **kwargs):
        return fake_instance

    monkeypatch.setattr("app.services.redis_client.aioredis.from_url", fake_from_url)

    client = RegimeRedisClient(settings)
    await client.connect()
    yield client
    await client.close()


@pytest.mark.asyncio
async def test_set_and_get_cached_regime_round_trip(fake_redis_client):
    from datetime import datetime, timezone

    from app.models.domain import RegimeResult, RegimeType

    result = RegimeResult(
        regime=RegimeType.TRENDING,
        confidence=0.77,
        sub_regimes=[RegimeType.BULLISH],
        symbol="NIFTY50",
        timeframe="5m",
        timestamp=datetime.now(timezone.utc),
        features={"adx": 30.0},
    )
    await fake_redis_client.set_cached_regime(result)
    fetched = await fake_redis_client.get_cached_regime("NIFTY50", "5m")
    assert fetched is not None
    assert fetched.regime == RegimeType.TRENDING
    assert fetched.confidence == pytest.approx(0.77)


@pytest.mark.asyncio
async def test_get_cached_regime_returns_none_when_absent(fake_redis_client):
    result = await fake_redis_client.get_cached_regime("UNKNOWN", "5m")
    assert result is None


@pytest.mark.asyncio
async def test_publish_regime_event_reaches_subscriber(fake_redis_client):
    from datetime import datetime, timezone

    from app.models.domain import RegimeResult, RegimeType

    pubsub = fake_redis_client.client.pubsub()
    await pubsub.subscribe("sg:regime:NIFTY50")

    result = RegimeResult(
        regime=RegimeType.RANGING,
        confidence=0.6,
        sub_regimes=[],
        symbol="NIFTY50",
        timeframe="5m",
        timestamp=datetime.now(timezone.utc),
        features={"adx": 10.0},
    )

    # Drain the subscribe confirmation message first.
    await pubsub.get_message(timeout=1)

    await fake_redis_client.publish_regime_event(result, event_type="regime_update")

    message = await pubsub.get_message(timeout=2)
    assert message is not None
    payload = json.loads(message["data"])
    assert payload["regime"] == "RANGING"
    assert payload["event_type"] == "regime_update"

    await pubsub.unsubscribe()
    await pubsub.aclose()


@pytest.mark.asyncio
async def test_subscribe_candles_builds_correct_channel_names(fake_redis_client):
    pubsub = await fake_redis_client.subscribe_candles([("NIFTY50", "5m"), ("RELIANCE", "5m")])
    assert "sg:market:candle:NIFTY50:5m" in pubsub.channels
    assert "sg:market:candle:RELIANCE:5m" in pubsub.channels
    await pubsub.unsubscribe()
    await pubsub.aclose()
