from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.core.engine import NoSignalsAvailableError, SignalAggregationEngine
from app.models.domain import AggregatedSignalResult, RegimeRef, SignalAction
from tests.conftest import make_raw_signal


@pytest.fixture
def mock_redis(example_raw_signals):
    redis_client = MagicMock()
    redis_client.collect_all_raw_signals = AsyncMock(return_value=example_raw_signals)
    redis_client.get_regime = AsyncMock(
        return_value=RegimeRef(
            regime="TRENDING", confidence=0.88, sub_regimes=[], timestamp=datetime.now(timezone.utc)
        )
    )
    redis_client.set_cached_result = AsyncMock()
    redis_client.publish_result = AsyncMock()
    return redis_client


@pytest.fixture
def mock_weight_store():
    store = MagicMock()
    store.refresh = AsyncMock()
    store.get_overrides = MagicMock(return_value={})
    return store


@pytest.fixture
def engine(settings, mock_redis, mock_weight_store):
    return SignalAggregationEngine(settings, mock_redis, mock_weight_store)


@pytest.fixture
def mock_session():
    session = MagicMock()
    session.add = MagicMock()
    session.flush = AsyncMock()
    return session


@pytest.mark.asyncio
async def test_aggregate_matches_brief_worked_example(engine, mock_session):
    result = await engine.aggregate(mock_session, "AAPL", "5m")

    assert isinstance(result, AggregatedSignalResult)
    assert result.symbol == "AAPL"
    assert result.regime == "TRENDING"
    assert result.final_signal == SignalAction.BUY
    assert set(result.contributors) == {"trend_following", "ml_prediction", "breakout"}
    assert "mean_reversion" not in result.contributors
    assert 0.0 < result.confidence <= 1.0

    # Contract shape check
    contract = result.to_contract_dict()
    assert contract["symbol"] == "AAPL"
    assert contract["final_signal"] == "BUY"
    assert isinstance(contract["confidence"], float)
    assert isinstance(contract["contributors"], list)


@pytest.mark.asyncio
async def test_aggregate_raises_when_no_signals_at_all(settings, mock_weight_store, mock_session):
    redis_client = MagicMock()
    redis_client.collect_all_raw_signals = AsyncMock(return_value={})
    engine = SignalAggregationEngine(settings, redis_client, mock_weight_store)

    with pytest.raises(NoSignalsAvailableError):
        await engine.aggregate(mock_session, "AAPL", "5m")


@pytest.mark.asyncio
async def test_aggregate_raises_when_all_signals_stale(settings, mock_weight_store, mock_session):
    stale_signals = {
        "trend_following": make_raw_signal(
            "trend_following", age_seconds=settings.SIGNAL_STALENESS_SECONDS + 500
        )
    }
    redis_client = MagicMock()
    redis_client.collect_all_raw_signals = AsyncMock(return_value=stale_signals)
    engine = SignalAggregationEngine(settings, redis_client, mock_weight_store)

    with pytest.raises(NoSignalsAvailableError):
        await engine.aggregate(mock_session, "AAPL", "5m")


@pytest.mark.asyncio
async def test_aggregate_persists_and_publishes(engine, mock_session, mock_redis):
    await engine.aggregate(mock_session, "AAPL", "5m")
    mock_redis.set_cached_result.assert_awaited_once()
    mock_redis.publish_result.assert_awaited_once()
    assert mock_session.add.called
    assert mock_session.flush.await_count >= 1


@pytest.mark.asyncio
async def test_aggregate_defaults_regime_to_unknown_when_unavailable(settings, mock_weight_store, mock_session, example_raw_signals):
    redis_client = MagicMock()
    redis_client.collect_all_raw_signals = AsyncMock(return_value=example_raw_signals)
    redis_client.get_regime = AsyncMock(return_value=None)
    redis_client.set_cached_result = AsyncMock()
    redis_client.publish_result = AsyncMock()
    engine = SignalAggregationEngine(settings, redis_client, mock_weight_store)

    result = await engine.aggregate(mock_session, "AAPL", "5m")
    assert result.regime == "UNKNOWN"
