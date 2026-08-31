"""
Model Serving / Prediction Layer.

Responsibilities:
  - Load champion model artifacts from disk into memory (LRU cache)
  - Run inference for a given FeatureVector or FeatureBatch
  - Ensemble predictions from multiple models (weighted by val_metric)
  - Apply regime filter (suppress signals in hostile regimes)
  - Cache predictions in Redis (TTL = PREDICTION_CACHE_TTL_SECONDS)
  - Record predictions to DB for outcome tracking and accuracy monitoring

Architecture:
  - Model weights are loaded once on first predict call per (symbol, model_type)
  - A background task refreshes the in-memory cache when the champion changes
  - Prediction latency target: < 500ms including cache check
"""
from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from functools import lru_cache
from typing import Any

import numpy as np

from app.core.config import settings
from app.core.logging import get_logger
from app.core.metrics import (
    prediction_cache_hits,
    prediction_confidence,
    prediction_latency_seconds,
    predictions_total,
    signals_published_total,
)
from app.core.redis import get_redis
from app.db import repository as repo
from app.models.domain import (
    EnsemblePrediction,
    FeatureBatch,
    FeatureVector,
    MLSignal,
    ModelPrediction,
    ModelType,
    ModelVersion,
    SignalDirection,
)

log = get_logger(__name__)

# In-memory model cache: (symbol, model_type) → (model_object, ModelVersion)
_model_cache: dict[tuple[str, str], tuple[Any, ModelVersion]] = {}


# ─────────────────────────────────────────────────────────────────────────────
# Model loader
# ─────────────────────────────────────────────────────────────────────────────

async def _load_champion(symbol: str, model_type: ModelType) -> tuple[Any, ModelVersion] | None:
    """Load champion model artifact. Returns (model, version) or None."""
    cache_key = (symbol, model_type.value)
    if cache_key in _model_cache:
        return _model_cache[cache_key]

    version = await repo.get_champion_model(symbol, model_type)
    if version is None or not version.artifact_path:
        log.debug("no_champion_model", symbol=symbol, model_type=model_type.value)
        return None

    import importlib
    trainer_map = {
        ModelType.XGBOOST: "app.training.xgboost_trainer.XGBoostTrainer",
        ModelType.LIGHTGBM: "app.training.lightgbm_trainer.LightGBMTrainer",
        ModelType.LSTM: "app.training.lstm_trainer.LSTMTrainer",
        ModelType.TRANSFORMER: "app.training.transformer_trainer.TransformerTrainer",
    }
    trainer_path = trainer_map[model_type]
    module_path, class_name = trainer_path.rsplit(".", 1)
    module = importlib.import_module(module_path)
    trainer = getattr(module, class_name)()

    try:
        model = trainer._load_model(version.artifact_path)
        _model_cache[cache_key] = (model, version)
        log.info(
            "champion_model_loaded",
            symbol=symbol,
            model_type=model_type.value,
            version_id=str(version.version_id),
        )
        return model, version
    except Exception:
        log.exception("champion_model_load_failed", symbol=symbol, model_type=model_type.value)
        return None


def invalidate_model_cache(symbol: str, model_type: ModelType) -> None:
    """Evict a model from the in-memory cache (called after champion promotion)."""
    _model_cache.pop((symbol, model_type.value), None)


# ─────────────────────────────────────────────────────────────────────────────
# Single-model prediction
# ─────────────────────────────────────────────────────────────────────────────

async def predict_single(
    symbol: str,
    model_type: ModelType,
    feature_vector: FeatureVector,
    feature_batch: FeatureBatch | None = None,
) -> ModelPrediction | None:
    """
    Run inference for one model type. Returns None if no champion available.
    """
    t0 = time.perf_counter()
    loaded = await _load_champion(symbol, model_type)
    if loaded is None:
        return None

    model, version = loaded

    # Build input array
    use_sequence = model_type in (ModelType.LSTM, ModelType.TRANSFORMER)
    if use_sequence and feature_batch and len(feature_batch.vectors) >= 20:
        arr = np.array([v.to_array() for v in feature_batch.vectors[-20:]], dtype=np.float32)
        X = arr[np.newaxis, ...]  # (1, seq_len, n_features)
    else:
        X = np.array([feature_vector.to_array()], dtype=np.float32)

    # Determine which trainer to use for predict_proba
    import importlib
    trainer_map = {
        ModelType.XGBOOST: "app.training.xgboost_trainer.XGBoostTrainer",
        ModelType.LIGHTGBM: "app.training.lightgbm_trainer.LightGBMTrainer",
        ModelType.LSTM: "app.training.lstm_trainer.LSTMTrainer",
        ModelType.TRANSFORMER: "app.training.transformer_trainer.TransformerTrainer",
    }
    module_path, class_name = trainer_map[model_type].rsplit(".", 1)
    trainer = getattr(importlib.import_module(module_path), class_name)()

    try:
        proba = trainer._predict_proba(model, X)  # shape (1, n_classes) or (1, 1)
    except Exception:
        log.exception("predict_proba_failed", symbol=symbol, model_type=model_type.value)
        return None

    elapsed_ms = (time.perf_counter() - t0) * 1000
    predictions_total.labels(model_type=model_type.value, symbol=symbol).inc()
    prediction_latency_seconds.labels(model_type=model_type.value).observe(elapsed_ms / 1000)

    # Interpret output
    n_classes = proba.shape[1] if proba.ndim > 1 else 1
    if n_classes == 3:
        # 0=DOWN, 1=FLAT, 2=UP (direction classification)
        class_idx = int(np.argmax(proba[0]))
        confidence = float(proba[0][class_idx])
        raw_probs = {"down": float(proba[0][0]), "flat": float(proba[0][1]), "up": float(proba[0][2])}
        direction_map = {0: SignalDirection.SHORT, 1: SignalDirection.FLAT, 2: SignalDirection.LONG}
        direction = direction_map[class_idx]
    elif n_classes == 2:
        # Binary UP/DOWN
        up_prob = float(proba[0][1]) if proba.shape[1] > 1 else float(proba[0][0])
        confidence = max(up_prob, 1 - up_prob)
        raw_probs = {"down": 1 - up_prob, "up": up_prob}
        direction = SignalDirection.LONG if up_prob > 0.5 else SignalDirection.SHORT
    else:
        # Regression output — interpret sign as direction
        pred_val = float(proba[0][0])
        direction = SignalDirection.LONG if pred_val > 0 else SignalDirection.SHORT
        confidence = min(abs(pred_val) * 10, 1.0)  # rough normalization
        raw_probs = {"predicted_return": pred_val}

    prediction_confidence.labels(model_type=model_type.value).observe(confidence)

    pred = ModelPrediction(
        model_version_id=version.version_id,
        model_type=model_type,
        symbol=symbol,
        timestamp=feature_vector.timestamp,
        direction=direction,
        confidence=confidence,
        raw_probabilities=raw_probs,
        latency_ms=elapsed_ms,
    )
    await repo.insert_prediction(pred)
    return pred


# ─────────────────────────────────────────────────────────────────────────────
# Ensemble
# ─────────────────────────────────────────────────────────────────────────────

async def predict_ensemble(
    symbol: str,
    feature_vector: FeatureVector,
    feature_batch: FeatureBatch | None = None,
    model_types: list[ModelType] | None = None,
) -> EnsemblePrediction | None:
    """
    Run all available model types and ensemble their predictions.

    Weighting: each model's vote is weighted by its champion val_metric.
    If all models agree → high confidence. If split → lower confidence.
    """
    if model_types is None:
        model_types = list(ModelType)

    # Check Redis cache first
    redis = await get_redis()
    cache_key = f"ml:pred:{symbol}:ensemble"
    cached = await redis.get(cache_key)
    if cached:
        prediction_cache_hits.labels(symbol=symbol).inc()
        try:
            data = json.loads(cached)
            return EnsemblePrediction.model_validate(data)
        except Exception:
            pass

    # Run all models concurrently
    import asyncio
    tasks = [
        predict_single(symbol, mt, feature_vector, feature_batch)
        for mt in model_types
    ]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    preds = [r for r in results if isinstance(r, ModelPrediction)]

    if not preds:
        log.debug("no_predictions_available", symbol=symbol)
        return None

    # Weighted voting by confidence * val_metric
    direction_votes: dict[SignalDirection, float] = {
        SignalDirection.LONG: 0.0,
        SignalDirection.SHORT: 0.0,
        SignalDirection.FLAT: 0.0,
    }
    total_weight = 0.0
    for pred in preds:
        version = await repo.get_champion_model(symbol, pred.model_type)
        weight = (version.val_metric or 0.5) * pred.confidence if version else pred.confidence
        direction_votes[pred.direction] += weight
        total_weight += weight

    if total_weight == 0:
        return None

    best_direction = max(direction_votes, key=lambda d: direction_votes[d])
    ensemble_confidence = direction_votes[best_direction] / total_weight

    ensemble = EnsemblePrediction(
        symbol=symbol,
        timestamp=feature_vector.timestamp,
        ensemble_direction=best_direction,
        ensemble_confidence=ensemble_confidence,
        model_predictions=preds,
    )

    # Cache result
    await redis.setex(cache_key, settings.prediction_cache_ttl_seconds, ensemble.model_dump_json())
    return ensemble


# ─────────────────────────────────────────────────────────────────────────────
# Signal publishing
# ─────────────────────────────────────────────────────────────────────────────

async def publish_signal(ensemble: EnsemblePrediction, regime_context: str | None = None) -> MLSignal | None:
    """
    Publish an MLSignal to Redis if confidence exceeds threshold.
    Also publishes regime update to sg:ml:regime:{symbol}.
    """
    if ensemble.ensemble_confidence < settings.serving_confidence_threshold:
        log.debug(
            "signal_below_threshold",
            symbol=ensemble.symbol,
            confidence=ensemble.ensemble_confidence,
            threshold=settings.serving_confidence_threshold,
        )
        return None

    signal = MLSignal(
        symbol=ensemble.symbol,
        direction=ensemble.ensemble_direction,
        confidence=ensemble.ensemble_confidence,
        model_types_used=[p.model_type.value for p in ensemble.model_predictions],
        regime_context=regime_context,
    )

    redis = await get_redis()
    channel = f"{settings.redis_ml_signals_prefix}:{ensemble.symbol}"
    await redis.publish(channel, signal.model_dump_json())

    signals_published_total.labels(
        symbol=ensemble.symbol,
        direction=ensemble.ensemble_direction.value,
    ).inc()

    log.info(
        "ml_signal_published",
        symbol=ensemble.symbol,
        direction=ensemble.ensemble_direction.value,
        confidence=round(ensemble.ensemble_confidence, 3),
        channel=channel,
    )
    return signal
