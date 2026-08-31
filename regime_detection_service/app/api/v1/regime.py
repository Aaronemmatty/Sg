"""REST endpoints for the regime detection service."""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_classifier, get_engine, get_redis
from app.api.v1.schemas import (
    BacktestRequest,
    BacktestResponse,
    RecalculateRequest,
    RecalculateResponse,
    RegimeResult,
    TransitionHistoryResponse,
)
from app.config import Settings, get_settings
from app.core.engine import InsufficientDataError, RegimeDetectionEngine
from app.core.security import verify_token
from app.db.session import get_session
from app.services.backtest_service import run_backtest
from app.services.redis_client import RegimeRedisClient

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/regime", tags=["regime"])


@router.get("/market", response_model=RegimeResult)
async def get_market_regime(
    timeframe: str = Query(default=None),
    engine: RegimeDetectionEngine = Depends(get_engine),
    redis_client: RegimeRedisClient = Depends(get_redis),
    settings: Settings = Depends(get_settings),
    session: AsyncSession = Depends(get_session),
    _claims: dict = Depends(verify_token),
):
    """Primary, market-wide (NIFTY50) regime — cached read with on-demand compute fallback."""
    tf = timeframe or settings.DEFAULT_TIMEFRAME
    cached = await redis_client.get_cached_regime(settings.PRIMARY_SYMBOL, tf)
    if cached is not None:
        return cached
    try:
        result = await engine.detect_market_wide(session, tf)
        await engine.persist_and_publish(session, result)
        return result
    except InsufficientDataError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc


@router.get("/{symbol}", response_model=RegimeResult)
async def get_symbol_regime(
    symbol: str,
    timeframe: str = Query(default=None),
    engine: RegimeDetectionEngine = Depends(get_engine),
    redis_client: RegimeRedisClient = Depends(get_redis),
    settings: Settings = Depends(get_settings),
    session: AsyncSession = Depends(get_session),
    _claims: dict = Depends(verify_token),
):
    """Current regime for a symbol (market-wide alias if symbol == PRIMARY_SYMBOL)."""
    tf = timeframe or settings.DEFAULT_TIMEFRAME
    cached = await redis_client.get_cached_regime(symbol, tf)
    if cached is not None:
        return cached
    try:
        return await engine.detect(session, symbol, tf)
    except InsufficientDataError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc


@router.get("/{symbol}/history", response_model=list[RegimeResult])
async def get_regime_history(
    symbol: str,
    timeframe: str = Query(default=None),
    limit: int = Query(default=100, le=1000),
    settings: Settings = Depends(get_settings),
    session: AsyncSession = Depends(get_session),
    _claims: dict = Depends(verify_token),
):
    from app.models.db import RegimeSnapshot

    tf = timeframe or settings.DEFAULT_TIMEFRAME
    stmt = (
        select(RegimeSnapshot)
        .where(RegimeSnapshot.symbol == symbol, RegimeSnapshot.timeframe == tf)
        .order_by(RegimeSnapshot.timestamp.desc())
        .limit(limit)
    )
    rows = (await session.execute(stmt)).scalars().all()
    return [
        RegimeResult(
            regime=r.regime,
            confidence=r.confidence,
            sub_regimes=r.sub_regimes,
            symbol=r.symbol,
            timeframe=r.timeframe,
            timestamp=r.timestamp,
            features=r.features,
            model_version=r.model_version,
            is_override=r.is_override,
        )
        for r in reversed(rows)
    ]


@router.get("/{symbol}/transitions", response_model=TransitionHistoryResponse)
async def get_transitions(
    symbol: str,
    timeframe: str = Query(default=None),
    limit: int = Query(default=50, le=500),
    settings: Settings = Depends(get_settings),
    session: AsyncSession = Depends(get_session),
    _claims: dict = Depends(verify_token),
):
    from app.models.db import RegimeTransitionRecord
    from app.models.domain import RegimeTransition

    tf = timeframe or settings.DEFAULT_TIMEFRAME
    stmt = (
        select(RegimeTransitionRecord)
        .where(RegimeTransitionRecord.symbol == symbol, RegimeTransitionRecord.timeframe == tf)
        .order_by(RegimeTransitionRecord.timestamp.desc())
        .limit(limit)
    )
    rows = (await session.execute(stmt)).scalars().all()
    transitions = [
        RegimeTransition(
            symbol=r.symbol,
            timeframe=r.timeframe,
            from_regime=r.from_regime,
            to_regime=r.to_regime,
            confidence=r.confidence,
            timestamp=r.timestamp,
            trigger_reason=r.trigger_reason,
        )
        for r in reversed(rows)
    ]
    return TransitionHistoryResponse(symbol=symbol, timeframe=tf, transitions=transitions)


@router.post("/recalculate", response_model=RecalculateResponse, status_code=status.HTTP_202_ACCEPTED)
async def recalculate(
    req: RecalculateRequest,
    engine: RegimeDetectionEngine = Depends(get_engine),
    settings: Settings = Depends(get_settings),
    session: AsyncSession = Depends(get_session),
    _claims: dict = Depends(verify_token),
):
    """Manual on-demand trigger, e.g. for operator debugging or after a backfill."""
    tf = req.timeframe or settings.DEFAULT_TIMEFRAME
    try:
        if req.symbol != settings.PRIMARY_SYMBOL:
            await engine.detect_market_wide(session, tf)
        await engine.detect(session, req.symbol, tf)
        return RecalculateResponse(triggered=[req.symbol])
    except InsufficientDataError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc


backtest_router = APIRouter(prefix="/api/v1/backtest", tags=["backtest"])


@backtest_router.post("/regime", response_model=BacktestResponse)
async def backtest_regime(
    req: BacktestRequest,
    classifier=Depends(get_classifier),
    settings: Settings = Depends(get_settings),
    session: AsyncSession = Depends(get_session),
    _claims: dict = Depends(verify_token),
):
    if req.end <= req.start:
        raise HTTPException(status_code=400, detail="end must be after start")
    return await run_backtest(session, settings, classifier, req.symbol, req.timeframe, req.start, req.end)
