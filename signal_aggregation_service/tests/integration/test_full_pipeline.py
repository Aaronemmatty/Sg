"""
Full-pipeline integration test, using fakeredis for the collection/cache/pub-sub layer
and a mocked SQLAlchemy session for persistence (no live Postgres in this environment).
Drives SignalAggregationEngine end-to-end through the brief's worked example plus a
conflicting/thin-consensus scenario, confirming contract-shaped output and DB writes.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.core.engine import NoSignalsAvailableError, SignalAggregationEngine
from app.models.db import AggregatedSignal
from app.services.redis_client import AggregationRedisClient
from app.services.weight_store import WeightStore
from tests.conftest import make_raw_signal


@pytest.fixture
async def pipeline_redis(settings, monkeypatch):
    import fakeredis.aioredis

    fake_instance = fakeredis.aioredis.FakeRedis(decode_responses=True)
    monkeypatch.setattr(
        "app.services.redis_client.aioredis.from_url", lambda *a, **k: fake_instance
    )
    client = AggregationRedisClient(settings)
    await client.connect()
    yield client
    await client.close()


@pytest.fixture
def pipeline_weight_store(settings):
    store = WeightStore(settings)
    store.refresh = AsyncMock()  # no DB to refresh from; cache stays empty -> static defaults only
    return store


@pytest.fixture
def pipeline_engine(settings, pipeline_redis, pipeline_weight_store):
    return SignalAggregationEngine(settings, pipeline_redis, pipeline_weight_store)


@pytest.fixture
def mock_session():
    session = MagicMock()
    session.add = MagicMock()
    session.flush = AsyncMock()
    return session


async def _seed_regime(pipeline_redis, symbol="AAPL", timeframe="5m", regime="TRENDING"):
    payload = {
        "regime": regime, "confidence": 0.85, "sub_regimes": [],
        "symbol": symbol, "timeframe": timeframe,
        "timestamp": datetime.now(timezone.utc).isoformat(), "features": {},
    }
    await pipeline_redis.client.set(f"regime:{symbol}:{timeframe}", json.dumps(payload))


async def _seed_signal(pipeline_redis, strategy, symbol="AAPL", timeframe="5m", action="BUY", confidence=0.8):
    raw = make_raw_signal(strategy, symbol=symbol, timeframe=timeframe, action=action, confidence=confidence)
    await pipeline_redis.client.set(f"signal:{strategy}:{symbol}:{timeframe}", json.dumps(raw))


@pytest.mark.asyncio
async def test_pipeline_full_worked_example(pipeline_engine, pipeline_redis, mock_session):
    await _seed_regime(pipeline_redis, regime="TRENDING")
    await _seed_signal(pipeline_redis, "trend_following", action="BUY", confidence=0.80)
    await _seed_signal(pipeline_redis, "mean_reversion", action="SELL", confidence=0.55)
    await _seed_signal(pipeline_redis, "ml_prediction", action="BUY", confidence=0.90)
    await _seed_signal(pipeline_redis, "breakout", action="BUY", confidence=0.75)

    result = await pipeline_engine.aggregate(mock_session, "AAPL", "5m")

    assert result.final_signal.value == "BUY"
    assert result.regime == "TRENDING"
    assert set(result.contributors) == {"trend_following", "ml_prediction", "breakout"}

    # Persisted exactly one AggregatedSignal snapshot.
    snapshot_calls = [c for c in mock_session.add.call_args_list if isinstance(c.args[0], AggregatedSignal)]
    assert len(snapshot_calls) == 1

    # Cached + published.
    cached = await pipeline_redis.get_cached_result("AAPL", "5m")
    assert cached is not None
    assert cached.final_signal == result.final_signal


@pytest.mark.asyncio
async def test_pipeline_custom_strategy_is_discovered_and_voted(pipeline_engine, pipeline_redis, mock_session):
    await _seed_regime(pipeline_redis, regime="RANGING")
    await _seed_signal(pipeline_redis, "mean_reversion", action="SELL", confidence=0.7)
    await _seed_signal(pipeline_redis, "rsi", action="SELL", confidence=0.6)
    await _seed_signal(pipeline_redis, "my_totally_custom_alpha", action="SELL", confidence=0.9)

    result = await pipeline_engine.aggregate(mock_session, "AAPL", "5m")

    assert "my_totally_custom_alpha" in result.votes
    assert result.final_signal.value == "SELL"


@pytest.mark.asyncio
async def test_pipeline_raises_when_symbol_has_no_signals(pipeline_engine, mock_session):
    with pytest.raises(NoSignalsAvailableError):
        await pipeline_engine.aggregate(mock_session, "NEVER_SEEDED_SYMBOL", "5m")


@pytest.mark.asyncio
async def test_pipeline_conflicting_signals_produce_lower_confidence_than_unanimous(
    pipeline_engine, pipeline_redis, mock_session
):
    await _seed_regime(pipeline_redis, symbol="CONFLICT", regime="TRENDING")
    await _seed_signal(pipeline_redis, "trend_following", symbol="CONFLICT", action="BUY", confidence=0.85)
    await _seed_signal(pipeline_redis, "breakout", symbol="CONFLICT", action="SELL", confidence=0.85)
    conflicted_result = await pipeline_engine.aggregate(mock_session, "CONFLICT", "5m")

    await _seed_regime(pipeline_redis, symbol="UNANIMOUS", regime="TRENDING")
    await _seed_signal(pipeline_redis, "trend_following", symbol="UNANIMOUS", action="BUY", confidence=0.85)
    await _seed_signal(pipeline_redis, "breakout", symbol="UNANIMOUS", action="BUY", confidence=0.85)
    unanimous_result = await pipeline_engine.aggregate(mock_session, "UNANIMOUS", "5m")

    assert conflicted_result.confidence < unanimous_result.confidence
