"""
Feature Store.

Responsibilities:
  - Cache latest FeatureVector per symbol in Redis (TTL-based)
  - Persist feature snapshots to sg_db for training dataset construction
  - Retrieve historical feature matrices for training
  - Store reference distributions (for drift monitoring)
  - Build train/val/test splits from historical features

The feature store is the single source of truth for ML inputs.
All models read from here; no model touches raw OHLCV directly.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

import numpy as np
import pandas as pd

from app.core.config import settings
from app.core.logging import get_logger
from app.core.redis import get_redis
from app.db.session import pool
from app.models.domain import FeatureVector

log = get_logger(__name__)

_FEATURE_KEY_PREFIX = "ml:features"
_REFERENCE_KEY_PREFIX = "ml:reference"


# ─────────────────────────────────────────────────────────────────────────────
# Redis cache
# ─────────────────────────────────────────────────────────────────────────────

async def cache_feature_vector(fv: FeatureVector) -> None:
    """Cache latest FeatureVector for a symbol in Redis."""
    redis = await get_redis()
    key = f"{_FEATURE_KEY_PREFIX}:{fv.symbol}:latest"
    await redis.setex(
        key,
        settings.feature_cache_ttl_seconds,
        fv.model_dump_json(),
    )


async def get_cached_feature_vector(symbol: str) -> FeatureVector | None:
    """Retrieve latest cached FeatureVector for a symbol."""
    redis = await get_redis()
    key = f"{_FEATURE_KEY_PREFIX}:{symbol}:latest"
    raw = await redis.get(key)
    if raw is None:
        return None
    try:
        return FeatureVector.model_validate_json(raw)
    except Exception:
        log.warning("feature_cache_parse_error", symbol=symbol)
        return None


async def cache_reference_distribution(
    symbol: str, model_type: str, feature_arrays: dict[str, list[float]]
) -> None:
    """Store training-time feature distributions for drift monitoring."""
    redis = await get_redis()
    key = f"{_REFERENCE_KEY_PREFIX}:{symbol}:{model_type}"
    await redis.setex(
        key,
        86400 * 30,  # 30 days — refreshed on each retrain
        json.dumps(feature_arrays),
    )


async def get_reference_distribution(
    symbol: str, model_type: str
) -> dict[str, list[float]] | None:
    """Retrieve reference feature distributions for PSI computation."""
    redis = await get_redis()
    key = f"{_REFERENCE_KEY_PREFIX}:{symbol}:{model_type}"
    raw = await redis.get(key)
    if raw is None:
        return None
    return json.loads(raw)


# ─────────────────────────────────────────────────────────────────────────────
# Postgres persistence
# ─────────────────────────────────────────────────────────────────────────────

async def persist_feature_snapshot(fv: FeatureVector) -> None:
    """Persist a feature vector snapshot to ml_feature_snapshots table."""
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO ml_feature_snapshots (symbol, timestamp, features, created_at)
            VALUES ($1, $2, $3, now())
            ON CONFLICT (symbol, timestamp) DO NOTHING
            """,
            fv.symbol,
            fv.timestamp,
            fv.model_dump_json(),
        )


async def get_training_dataset(
    symbol: str,
    limit: int = 5000,
    since: datetime | None = None,
) -> pd.DataFrame:
    """
    Retrieve historical feature snapshots as a DataFrame for model training.

    Returns a DataFrame with all feature columns plus a 'timestamp' column,
    sorted oldest-first. Returns empty DataFrame if no data.
    """
    async with pool.acquire() as conn:
        if since:
            rows = await conn.fetch(
                """
                SELECT timestamp, features FROM ml_feature_snapshots
                WHERE symbol = $1 AND timestamp >= $2
                ORDER BY timestamp ASC LIMIT $3
                """,
                symbol, since, limit,
            )
        else:
            rows = await conn.fetch(
                """
                SELECT timestamp, features FROM ml_feature_snapshots
                WHERE symbol = $1
                ORDER BY timestamp ASC LIMIT $2
                """,
                symbol, limit,
            )

    if not rows:
        return pd.DataFrame()

    records = []
    for row in rows:
        try:
            data = json.loads(row["features"])
            data["timestamp"] = row["timestamp"]
            records.append(data)
        except Exception:
            continue

    if not records:
        return pd.DataFrame()

    df = pd.DataFrame(records)
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
    df = df.set_index("timestamp").sort_index()
    return df


async def get_feature_count(symbol: str) -> int:
    """Count available feature snapshots for a symbol."""
    async with pool.acquire() as conn:
        result = await conn.fetchval(
            "SELECT COUNT(*) FROM ml_feature_snapshots WHERE symbol = $1",
            symbol,
        )
        return result or 0


# ─────────────────────────────────────────────────────────────────────────────
# Dataset splitting
# ─────────────────────────────────────────────────────────────────────────────

def split_dataset(
    X: np.ndarray,
    y: np.ndarray,
    test_split: float = 0.2,
    val_split: float = 0.1,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """
    Temporal train/val/test split — NO shuffle (time series data).

    Returns: X_train, X_val, X_test, y_train, y_val, y_test
    """
    n = len(X)
    test_n = max(1, int(n * test_split))
    val_n = max(1, int(n * val_split))
    train_n = n - val_n - test_n

    if train_n < 10:
        raise ValueError(f"Too few samples for split: n={n}")

    X_train = X[:train_n]
    X_val = X[train_n:train_n + val_n]
    X_test = X[train_n + val_n:]
    y_train = y[:train_n]
    y_val = y[train_n:train_n + val_n]
    y_test = y[train_n + val_n:]

    return X_train, X_val, X_test, y_train, y_val, y_test


def build_sequences(
    X: np.ndarray,
    y: np.ndarray,
    seq_len: int,
) -> tuple[np.ndarray, np.ndarray]:
    """
    Build overlapping sequences of shape (n_samples, seq_len, n_features)
    for LSTM/Transformer. y aligned to the last timestep of each sequence.
    """
    n_samples = len(X) - seq_len
    if n_samples <= 0:
        raise ValueError(f"Not enough rows ({len(X)}) for seq_len={seq_len}")

    X_seq = np.stack([X[i:i + seq_len] for i in range(n_samples)])
    y_seq = y[seq_len:]
    return X_seq, y_seq
