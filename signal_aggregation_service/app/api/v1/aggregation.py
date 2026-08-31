"""REST endpoints for signal_aggregation_service."""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_engine, get_redis, get_weight_store
from app.api.v1.schemas import (
    AggregatedSignalResult,
    ContractExampleResponse,
    RecalculateRequest,
    RecalculateResponse,
    WeightOverrideRequest,
    WeightOverrideResponse,
)
from app.config import DEFAULT_REGIME_WEIGHTS, FALLBACK_WEIGHTS, Settings, get_settings
from app.core.engine import NoSignalsAvailableError, SignalAggregationEngine
from app.core.security import verify_token
from app.db.session import get_session
from app.services.redis_client import AggregationRedisClient
from app.services.weight_store import WeightStore

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/signal", tags=["signal-aggregation"])
weights_router = APIRouter(prefix="/api/v1/weights", tags=["weights"])


@router.get("/{symbol}", response_model=AggregatedSignalResult)
async def get_signal(
    symbol: str,
    timeframe: str = Query(default=None),
    engine: SignalAggregationEngine = Depends(get_engine),
    redis_client: AggregationRedisClient = Depends(get_redis),
    settings: Settings = Depends(get_settings),
    session: AsyncSession = Depends(get_session),
    _claims: dict = Depends(verify_token),
):
    """Current consensus signal for a symbol — cached read with on-demand compute fallback."""
    tf = timeframe or settings.DEFAULT_TIMEFRAME
    cached = await redis_client.get_cached_result(symbol, tf)
    if cached is not None:
        return cached
    try:
        return await engine.aggregate(session, symbol, tf)
    except NoSignalsAvailableError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc


@router.get("/{symbol}/contract", response_model=ContractExampleResponse)
async def get_signal_contract_shape(
    symbol: str,
    timeframe: str = Query(default=None),
    engine: SignalAggregationEngine = Depends(get_engine),
    redis_client: AggregationRedisClient = Depends(get_redis),
    settings: Settings = Depends(get_settings),
    session: AsyncSession = Depends(get_session),
    _claims: dict = Depends(verify_token),
):
    """Returns exactly the minimal output shape from the brief's example."""
    tf = timeframe or settings.DEFAULT_TIMEFRAME
    cached = await redis_client.get_cached_result(symbol, tf)
    result = cached or await engine.aggregate(session, symbol, tf)
    return ContractExampleResponse(**result.to_contract_dict())


@router.get("/{symbol}/history", response_model=list[AggregatedSignalResult])
async def get_signal_history(
    symbol: str,
    timeframe: str = Query(default=None),
    limit: int = Query(default=100, le=1000),
    settings: Settings = Depends(get_settings),
    session: AsyncSession = Depends(get_session),
    _claims: dict = Depends(verify_token),
):
    from app.models.db import AggregatedSignal

    tf = timeframe or settings.DEFAULT_TIMEFRAME
    stmt = (
        select(AggregatedSignal)
        .where(AggregatedSignal.symbol == symbol, AggregatedSignal.timeframe == tf)
        .order_by(AggregatedSignal.timestamp.desc())
        .limit(limit)
    )
    rows = (await session.execute(stmt)).scalars().all()
    return [
        AggregatedSignalResult(
            symbol=r.symbol,
            timeframe=r.timeframe,
            final_signal=r.final_signal,
            confidence=r.confidence,
            contributors=r.contributors,
            regime=r.regime,
            net_score=r.net_score,
            agreement_ratio=r.agreement_ratio,
            votes=r.votes,
            timestamp=r.timestamp,
            weights_version=r.weights_version,
        )
        for r in reversed(rows)
    ]


@router.post("/recalculate", response_model=RecalculateResponse, status_code=status.HTTP_202_ACCEPTED)
async def recalculate(
    req: RecalculateRequest,
    engine: SignalAggregationEngine = Depends(get_engine),
    settings: Settings = Depends(get_settings),
    session: AsyncSession = Depends(get_session),
    _claims: dict = Depends(verify_token),
):
    tf = req.timeframe or settings.DEFAULT_TIMEFRAME
    try:
        await engine.aggregate(session, req.symbol, tf)
        return RecalculateResponse(triggered=[req.symbol])
    except NoSignalsAvailableError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc


# --- Weights CRUD --------------------------------------------------------------------


@weights_router.get("/{regime}", response_model=WeightOverrideResponse)
async def get_weights(
    regime: str,
    weight_store: WeightStore = Depends(get_weight_store),
    session: AsyncSession = Depends(get_session),
    _claims: dict = Depends(verify_token),
):
    static_defaults = DEFAULT_REGIME_WEIGHTS.get(regime.upper(), FALLBACK_WEIGHTS)
    overrides = await weight_store.get_all_for_regime(session, regime.upper())
    merged = {**static_defaults, **overrides}
    source = "db_override" if overrides else "static_default"
    return WeightOverrideResponse(regime=regime.upper(), effective_weights=merged, source=source)


@weights_router.put("/{regime}", response_model=WeightOverrideResponse, status_code=status.HTTP_200_OK)
async def set_weights(
    regime: str,
    req: WeightOverrideRequest,
    weight_store: WeightStore = Depends(get_weight_store),
    redis_client: AggregationRedisClient = Depends(get_redis),
    session: AsyncSession = Depends(get_session),
    claims: dict = Depends(verify_token),
):
    if any(w < 0 for w in req.weights.values()):
        raise HTTPException(status_code=400, detail="weights must be non-negative")

    regime_key = regime.upper()
    updated = await weight_store.upsert(session, regime_key, req.weights, updated_by=claims.get("sub"))
    await redis_client.publish_weights_updated(regime_key)

    static_defaults = DEFAULT_REGIME_WEIGHTS.get(regime_key, FALLBACK_WEIGHTS)
    merged = {**static_defaults, **updated}
    return WeightOverrideResponse(regime=regime_key, effective_weights=merged, source="merged")
