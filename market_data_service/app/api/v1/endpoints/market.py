"""Market data REST endpoints — live quotes, historical bars, subscriptions."""

from __future__ import annotations

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user
from app.core.calendar import is_market_open, is_preopen, seconds_to_market_open
from app.core.config import get_settings
from app.core.redis import get_all_ticks, get_cached_tick, get_feed_status
from app.core.types import Timeframe
from app.db.session import get_db
from app.feeds.kite.instruments import get_registry
from app.schemas.market import (
    BackfillRequest,
    BackfillResponse,
    BarsResponse,
    FeedStatus,
    InstrumentInfo,
    InstrumentSearchResponse,
    MarketStatus,
    OHLCVBar,
    SubscribeRequest,
    SubscribeResponse,
    TickResponse,
    UnsubscribeRequest,
)
from app.services.engine import get_engine
from app.services.historical import HistoricalService
from sg_security.validation import validate_symbol, validate_timeframe

settings = get_settings()
router = APIRouter(prefix="/market", tags=["Market Data"])


# ── Live quotes ───────────────────────────────────────────────────────────────

@router.get("/quote/{symbol:path}", response_model=TickResponse, summary="Get latest tick for a symbol")
async def get_quote(symbol: str = Path(...), _user = Depends(get_current_user)) -> TickResponse:
    """
    Get the most recent tick for a symbol.
    symbol format: NSE:RELIANCE or just RELIANCE
    """
    if ":" not in symbol:
        symbol = f"NSE:{symbol}"

    tick = await get_cached_tick(symbol)
    if not tick:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No live data for {symbol}. Ensure it is subscribed.",
        )
    return TickResponse(**tick)


@router.post("/quotes", response_model=dict[str, TickResponse], summary="Get latest ticks for multiple symbols")
async def get_quotes(symbols: list[str], _user = Depends(get_current_user)) -> dict[str, TickResponse]:
    normalised = [s if ":" in s else f"NSE:{s}" for s in symbols]
    ticks = await get_all_ticks(normalised)
    return {sym: TickResponse(**data) for sym, data in ticks.items()}


# ── Historical bars ───────────────────────────────────────────────────────────

@router.get("/bars/{symbol:path}", response_model=BarsResponse, summary="Get historical OHLCV bars")
async def get_bars(
    symbol: str = Path(...),
    timeframe: str = Query("1m", description="Timeframe: 1m 3m 5m 15m 30m 1h 4h 1D"),
    from_date: date = Query(...),
    to_date: date = Query(default_factory=date.today),
    limit: int = Query(1000, ge=1, le=5000),
    db: AsyncSession = Depends(get_db),
    _user = Depends(get_current_user),
) -> BarsResponse:
    symbol = validate_symbol(symbol)
    if ":" not in symbol:
        symbol = f"NSE:{symbol}"

    timeframe = validate_timeframe(timeframe)
    tf_map = {"1m": 1, "3m": 3, "5m": 5, "15m": 15,
               "30m": 30, "1h": 60, "4h": 240, "1D": 375}
    tf_minutes = tf_map.get(timeframe)
    if not tf_minutes:
        raise HTTPException(status_code=422, detail=f"Invalid timeframe: {timeframe}")

    tf = Timeframe(tf_minutes)
    svc = HistoricalService(db)
    bars = await svc.get_bars(symbol, tf, from_date, to_date, limit)

    return BarsResponse(
        symbol=symbol,
        timeframe=timeframe,
        from_date=str(from_date),
        to_date=str(to_date),
        count=len(bars),
        bars=[OHLCVBar(**b.to_dict()) for b in bars],
    )


# ── Subscriptions ─────────────────────────────────────────────────────────────

@router.post("/subscribe", response_model=SubscribeResponse, summary="Subscribe to live feed")
async def subscribe(body: SubscribeRequest, _user = Depends(get_current_user)) -> SubscribeResponse:
    engine = get_engine()
    token_map = await engine.subscribe(body.symbols)

    succeeded = list(token_map.keys())
    failed = [s if ":" in s else f"NSE:{s}" for s in body.symbols
              if (s if ":" in s else f"NSE:{s}") not in token_map]

    return SubscribeResponse(
        subscribed=token_map,
        failed=failed,
        total=len(succeeded),
    )


@router.post("/unsubscribe", status_code=status.HTTP_204_NO_CONTENT, response_model=None, summary="Unsubscribe from live feed")
async def unsubscribe(body: UnsubscribeRequest, _user = Depends(get_current_user)) -> None:
    engine = get_engine()
    await engine.unsubscribe(body.symbols)


# ── Backfill ──────────────────────────────────────────────────────────────────

@router.post("/backfill", response_model=BackfillResponse, summary="Backfill historical OHLCV data")
async def backfill(
    body: BackfillRequest,
    db: AsyncSession = Depends(get_db),
    _user = Depends(get_current_user),
) -> BackfillResponse:
    tf_map = {"1m": 1, "3m": 3, "5m": 5, "15m": 15,
               "30m": 30, "1h": 60, "4h": 240, "1D": 375}
    tf_minutes = tf_map.get(body.timeframe)
    if not tf_minutes:
        raise HTTPException(status_code=422, detail=f"Invalid timeframe: {body.timeframe}")

    symbol = body.symbol if ":" in body.symbol else f"NSE:{body.symbol}"
    tf = Timeframe(tf_minutes)
    svc = HistoricalService(db)

    try:
        bars_written = await svc.backfill(
            symbol=symbol,
            timeframe=tf,
            from_date=body.from_date,
            to_date=body.to_date,
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

    return BackfillResponse(
        symbol=symbol,
        timeframe=body.timeframe,
        bars_written=bars_written,
        message=f"Backfill complete: {bars_written} bars written.",
    )


# ── Instruments ───────────────────────────────────────────────────────────────

@router.get("/instruments/search", response_model=InstrumentSearchResponse, summary="Search NSE instruments")
async def search_instruments(
    q: str = Query(..., min_length=1, max_length=20),
    limit: int = Query(20, ge=1, le=100),
    _user = Depends(get_current_user),
) -> InstrumentSearchResponse:
    registry = get_registry()
    results = registry.search(q.upper(), limit=limit)
    return InstrumentSearchResponse(
        query=q,
        results=[
            InstrumentInfo(
                instrument_token=i.instrument_token,
                trading_symbol=i.trading_symbol,
                name=i.name,
                exchange=i.exchange,
                instrument_type=i.instrument_type,
                lot_size=i.lot_size,
                tick_size=i.tick_size,
            )
            for i in results
        ],
        count=len(results),
    )


@router.get("/instruments/{symbol:path}", response_model=InstrumentInfo, summary="Get instrument details")
async def get_instrument(symbol: str = Path(...), _user = Depends(get_current_user)) -> InstrumentInfo:
    symbol = validate_symbol(symbol)
    registry = get_registry()
    inst = registry.get_by_symbol(symbol)
    if not inst:
        raise HTTPException(status_code=404, detail=f"Instrument not found: {symbol}")
    return InstrumentInfo(
        instrument_token=inst.instrument_token,
        trading_symbol=inst.trading_symbol,
        name=inst.name,
        exchange=inst.exchange,
        instrument_type=inst.instrument_type,
        lot_size=inst.lot_size,
        tick_size=inst.tick_size,
    )


# ── Status ────────────────────────────────────────────────────────────────────

@router.get("/status", response_model=FeedStatus, summary="Feed and engine status")
async def feed_status(_user = Depends(get_current_user)) -> FeedStatus:
    engine = get_engine()
    feed_info = await get_feed_status()
    stats = engine.get_stats()

    return FeedStatus(
        status=feed_info.get("status", "unknown"),
        mode=settings.KITE_MODE,
        subscribed_symbols=engine.subscribed_count,
        market_open=is_market_open(),
        feed_stats=stats.get("feed"),
        aggregator_stats=stats.get("aggregator"),
        writer_stats=stats.get("writer"),
    )


@router.get("/market-status", response_model=MarketStatus, summary="NSE market open/close status")
async def market_status(_user = Depends(get_current_user)) -> MarketStatus:
    open_ = is_market_open()
    preopen = is_preopen()
    next_open = None if open_ else seconds_to_market_open()

    if open_:
        msg = "NSE market is open for trading."
    elif preopen:
        msg = "NSE pre-open session in progress."
    else:
        secs = seconds_to_market_open()
        mins = int(secs // 60)
        msg = f"NSE market closed. Opens in {mins} minutes."

    return MarketStatus(
        is_open=open_,
        is_preopen=preopen,
        next_open_in_seconds=next_open,
        message=msg,
    )
