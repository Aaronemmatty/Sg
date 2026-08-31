"""Shared fixtures for unit + integration tests."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from app.config import Settings


@pytest.fixture
def settings() -> Settings:
    return Settings(
        DATABASE_URL="sqlite+aiosqlite:///:memory:",
        REDIS_URL="redis://localhost:6379/15",
        AUTH_REQUIRED=False,
        MIN_BARS_REQUIRED=60,
    )


def _make_ohlcv(n: int, *, trend: float = 0.0, vol: float = 0.005, seed: int = 7) -> pd.DataFrame:
    """
    Synthetic OHLCV generator for deterministic unit tests.
    trend: per-bar drift (e.g. 0.001 = +0.1%/bar trending up)
    vol:   per-bar return std-dev (noise)
    """
    rng = np.random.default_rng(seed)
    rets = trend + rng.normal(0, vol, n)
    close = 100 * np.cumprod(1 + rets)
    high = close * (1 + np.abs(rng.normal(0, vol / 2, n)))
    low = close * (1 - np.abs(rng.normal(0, vol / 2, n)))
    open_ = np.r_[close[0], close[:-1]]
    volume = rng.integers(10_000, 50_000, n)
    timestamps = pd.date_range("2026-01-01", periods=n, freq="5min", tz="UTC")
    return pd.DataFrame(
        {
            "timestamp": timestamps,
            "open": open_,
            "high": high,
            "low": low,
            "close": close,
            "volume": volume,
        }
    )


@pytest.fixture
def trending_ohlcv() -> pd.DataFrame:
    return _make_ohlcv(150, trend=0.0015, vol=0.002, seed=1)


@pytest.fixture
def ranging_ohlcv() -> pd.DataFrame:
    """Mean-reverting, low-trend, compressed-range series."""
    rng = np.random.default_rng(3)
    n = 150
    base = 100 + 0.5 * np.sin(np.linspace(0, 12, n))
    noise = rng.normal(0, 0.05, n)
    close = base + noise
    high = close + np.abs(rng.normal(0, 0.05, n))
    low = close - np.abs(rng.normal(0, 0.05, n))
    open_ = np.r_[close[0], close[:-1]]
    volume = rng.integers(10_000, 20_000, n)
    timestamps = pd.date_range("2026-01-01", periods=n, freq="5min", tz="UTC")
    return pd.DataFrame(
        {"timestamp": timestamps, "open": open_, "high": high, "low": low, "close": close, "volume": volume}
    )


@pytest.fixture
def high_vol_ohlcv() -> pd.DataFrame:
    return _make_ohlcv(150, trend=0.0, vol=0.03, seed=5)


@pytest.fixture
def bearish_ohlcv() -> pd.DataFrame:
    return _make_ohlcv(150, trend=-0.0015, vol=0.002, seed=2)
