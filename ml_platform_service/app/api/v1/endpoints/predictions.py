"""
Prediction API endpoints.

POST /predict/{symbol}          — on-demand ensemble prediction
POST /predict/{symbol}/{model}  — single model prediction
GET  /predict/history           — recent predictions log
GET  /features/{symbol}         — latest cached feature vector
POST /features/{symbol}/refresh — force feature recomputation
GET  /features/{symbol}/drift   — latest drift report
POST /outcomes                  — record actual outcome for a prediction
"""
from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Body, Depends, HTTPException, Query

from app.auth import CurrentUser, get_current_user
from app.core.logging import get_logger
from app.db import repository as repo
from app.features.store import get_cached_feature_vector
from app.models.domain import ModelType
from app.monitoring.drift_monitor import (
    compute_drift_report,
    record_prediction_outcome,
    update_rolling_accuracy,
)
from app.serving.predictor import predict_ensemble, predict_single, publish_signal

log = get_logger(__name__)
router = APIRouter(tags=["predictions"])


@router.post("/predict/{symbol}")
async def predict_symbol(
    symbol: str,
    model_types: Annotated[list[ModelType] | None, Body(embed=True)] = None,
    publish: Annotated[bool, Body(embed=True)] = False,
    _user: CurrentUser = Depends(get_current_user),
):
    """
    Run ensemble prediction for a symbol using latest cached features.
    Optionally publish the signal to Redis.
    """
    fv = await get_cached_feature_vector(symbol.upper())
    if fv is None:
        raise HTTPException(
            status_code=404,
            detail=f"No cached features for {symbol.upper()}. Wait for next candle or call /features/{symbol}/refresh.",
        )

    ensemble = await predict_ensemble(symbol.upper(), fv, model_types=model_types)
    if ensemble is None:
        raise HTTPException(
            status_code=503,
            detail="No champion models available. Train a model first.",
        )

    signal = None
    if publish:
        signal = await publish_signal(ensemble)

    return {
        "ensemble": ensemble.model_dump(mode="json"),
        "signal_published": signal is not None,
    }


@router.post("/predict/{symbol}/{model_type}")
async def predict_single_model(
    symbol: str,
    model_type: ModelType,
    _user: CurrentUser = Depends(get_current_user),
):
    """Run prediction for a single model type."""
    fv = await get_cached_feature_vector(symbol.upper())
    if fv is None:
        raise HTTPException(status_code=404, detail=f"No cached features for {symbol.upper()}")

    pred = await predict_single(symbol.upper(), model_type, fv)
    if pred is None:
        raise HTTPException(
            status_code=503,
            detail=f"No champion {model_type.value} model for {symbol.upper()}",
        )
    return pred.model_dump(mode="json")


@router.get("/predict/history")
async def prediction_history(
    symbol: str | None = Query(default=None),
    model_type: str | None = Query(default=None),
    limit: int = Query(default=100, le=500),
    _user: CurrentUser = Depends(get_current_user),
):
    preds = await repo.list_predictions(symbol=symbol, model_type=model_type, limit=limit)
    return {"predictions": preds, "count": len(preds)}


@router.get("/features/{symbol}")
async def get_features(
    symbol: str,
    _user: CurrentUser = Depends(get_current_user),
):
    """Return the latest cached feature vector for a symbol."""
    fv = await get_cached_feature_vector(symbol.upper())
    if fv is None:
        raise HTTPException(status_code=404, detail=f"No cached features for {symbol.upper()}")
    return fv.model_dump(mode="json")


@router.post("/features/{symbol}/refresh")
async def refresh_features(
    symbol: str,
    _user: CurrentUser = Depends(get_current_user),
):
    """Force a feature recomputation for a symbol by fetching fresh OHLCV data."""
    from app.features.engineer import FeatureEngineer
    from app.features.store import cache_feature_vector, persist_feature_snapshot
    from app.services.market_data_client import market_data_client
    from app.core.config import settings

    df = await market_data_client.get_ohlcv(symbol.upper(), bars=settings.feature_lookback_bars)
    if df is None or len(df) < 50:
        raise HTTPException(
            status_code=503,
            detail=f"Unable to fetch sufficient OHLCV data for {symbol.upper()}",
        )

    engineer = FeatureEngineer()
    fv = engineer.compute_latest(df, symbol.upper())
    await cache_feature_vector(fv)
    await persist_feature_snapshot(fv)
    return {"symbol": symbol.upper(), "timestamp": fv.timestamp.isoformat(), "refreshed": True}


@router.get("/features/{symbol}/drift")
async def get_drift_report(
    symbol: str,
    model_type: ModelType = Query(default=ModelType.XGBOOST),
    _user: CurrentUser = Depends(get_current_user),
):
    """Return the latest drift report for a symbol and model type."""
    report = await repo.get_latest_drift_report(symbol.upper(), model_type.value)
    if report is None:
        raise HTTPException(
            status_code=404,
            detail=f"No drift report for {symbol.upper()}/{model_type.value}",
        )
    return report


@router.post("/outcomes")
async def record_outcome(
    prediction_id: Annotated[uuid.UUID, Body(embed=True)],
    symbol: Annotated[str, Body(embed=True)],
    model_type: Annotated[ModelType, Body(embed=True)],
    actual_return: Annotated[float, Body(embed=True)],
    _user: CurrentUser = Depends(get_current_user),
):
    """Record ground-truth outcome for a prior prediction (called after bar closes)."""
    outcome = await record_prediction_outcome(
        prediction_id=prediction_id,
        symbol=symbol.upper(),
        model_type=model_type,
        actual_return=actual_return,
    )
    accuracy = await update_rolling_accuracy(symbol.upper(), model_type)
    return {
        "outcome": outcome.model_dump(mode="json"),
        "rolling_accuracy": round(accuracy, 4),
    }
