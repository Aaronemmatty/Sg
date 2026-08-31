"""Shared fixtures for unit + integration tests."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.config import Settings


@pytest.fixture
def settings() -> Settings:
    return Settings(
        DATABASE_URL="sqlite+aiosqlite:///:memory:",
        REDIS_URL="redis://localhost:6379/15",
        AUTH_REQUIRED=False,
    )


def make_raw_signal(
    strategy: str,
    symbol: str = "AAPL",
    timeframe: str = "5m",
    action: str = "BUY",
    confidence: float = 0.8,
    age_seconds: float = 0,
) -> dict:
    ts = datetime.now(timezone.utc) - timedelta(seconds=age_seconds)
    return {
        "strategy": strategy,
        "symbol": symbol,
        "timeframe": timeframe,
        "action": action,
        "confidence": confidence,
        "timestamp": ts.isoformat(),
    }


@pytest.fixture
def example_raw_signals() -> dict[str, dict]:
    """Matches the brief's worked example exactly."""
    return {
        "trend_following": make_raw_signal("trend_following", action="BUY", confidence=0.80),
        "mean_reversion": make_raw_signal("mean_reversion", action="SELL", confidence=0.55),
        "ml_prediction": make_raw_signal("ml_prediction", action="BUY", confidence=0.90),
        "breakout": make_raw_signal("breakout", action="BUY", confidence=0.75),
    }
