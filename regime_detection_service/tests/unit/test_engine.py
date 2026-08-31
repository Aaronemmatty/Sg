from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.core.classifier import HybridClassifier
from app.core.engine import InsufficientDataError, RegimeDetectionEngine
from app.models.domain import RegimeResult, RegimeType


@pytest.fixture
def mock_redis():
    redis_client = MagicMock()
    redis_client.get_cached_regime = AsyncMock(return_value=None)
    redis_client.set_cached_regime = AsyncMock()
    redis_client.publish_regime_event = AsyncMock()
    redis_client.get_latest_tick = AsyncMock(return_value=None)
    return redis_client


@pytest.fixture
def classifier(tmp_path):
    return HybridClassifier(model_path=str(tmp_path / "missing.joblib"))


@pytest.fixture
def engine(settings, mock_redis, classifier):
    return RegimeDetectionEngine(settings, mock_redis, classifier)


@pytest.mark.asyncio
async def test_detect_single_raises_on_insufficient_bars(engine, monkeypatch, settings):
    import pandas as pd

    async def fake_get_recent_bars(*args, **kwargs):
        return pd.DataFrame(columns=["timestamp", "open", "high", "low", "close", "volume"])

    monkeypatch.setattr("app.services.market_data_client.get_recent_bars", fake_get_recent_bars)

    session = MagicMock()
    with pytest.raises(InsufficientDataError):
        await engine._detect_single(session, "NIFTY50", "5m", breadth=None, is_override=False)


@pytest.mark.asyncio
async def test_detect_single_returns_contract_shaped_result(engine, monkeypatch, settings, trending_ohlcv):
    async def fake_get_recent_bars(*args, **kwargs):
        return trending_ohlcv

    monkeypatch.setattr("app.services.market_data_client.get_recent_bars", fake_get_recent_bars)

    session = MagicMock()
    result = await engine._detect_single(session, "NIFTY50", "5m", breadth=None, is_override=False)

    assert isinstance(result, RegimeResult)
    assert result.symbol == "NIFTY50"
    assert result.timeframe == "5m"
    assert isinstance(result.regime, RegimeType)
    assert 0.0 <= result.confidence <= 1.0
    assert "adx" in result.features
    assert result.timestamp.tzinfo is not None


def test_divergence_score_zero_when_identical():
    now = datetime.now(timezone.utc)
    market = RegimeResult(
        regime=RegimeType.TRENDING, confidence=0.8, sub_regimes=[], symbol="NIFTY50",
        timeframe="5m", timestamp=now, features={"trend_slope": 0.01, "atr_pct": 0.005},
    )
    symbol = RegimeResult(
        regime=RegimeType.TRENDING, confidence=0.8, sub_regimes=[], symbol="RELIANCE",
        timeframe="5m", timestamp=now, features={"trend_slope": 0.01, "atr_pct": 0.005},
    )
    score = RegimeDetectionEngine._divergence_score(market, symbol)
    assert score == 0.0


def test_divergence_score_high_when_opposite_structure_and_direction():
    now = datetime.now(timezone.utc)
    market = RegimeResult(
        regime=RegimeType.TRENDING, confidence=0.8, sub_regimes=[], symbol="NIFTY50",
        timeframe="5m", timestamp=now, features={"trend_slope": 0.01, "atr_pct": 0.005},
    )
    symbol = RegimeResult(
        regime=RegimeType.RANGING, confidence=0.8, sub_regimes=[], symbol="RELIANCE",
        timeframe="5m", timestamp=now, features={"trend_slope": -0.01, "atr_pct": 0.02},
    )
    score = RegimeDetectionEngine._divergence_score(market, symbol)
    assert score > 0.6
