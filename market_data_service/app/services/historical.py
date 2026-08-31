"""Historical data service — backfill and on-demand fetch."""

from __future__ import annotations

import asyncio
from datetime import date, timedelta
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.logging import get_logger
from app.core.types import OHLCV, Timeframe
from app.feeds.kite.historical import HistoricalFetcher
from app.feeds.kite.instruments import get_registry
from app.publishers.postgres import CandleWriter
from sg_db.models.market_data import MarketBar

settings = get_settings()
log = get_logger(__name__)


class HistoricalService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self._fetcher = HistoricalFetcher()

    async def backfill(
        self,
        symbol: str,
        timeframe: Timeframe,
        from_date: date,
        to_date: Optional[date] = None,
    ) -> int:
        """
        Backfill OHLCV data for a symbol. Returns number of bars written.
        Skips date ranges already present in DB.
        """
        to_date = to_date or date.today()
        registry = get_registry()
        inst = registry.get_by_symbol(symbol)

        if not inst:
            raise ValueError(f"Symbol not found in registry: {symbol}")

        # Find gaps — dates we already have
        existing_dates = await self._get_existing_dates(symbol, timeframe, from_date, to_date)

        # Determine effective range excluding already-stored data
        effective_from = from_date
        for d in sorted(existing_dates):
            if d == effective_from:
                effective_from += timedelta(days=1)
            else:
                break

        if effective_from > to_date:
            log.info("backfill_already_complete", symbol=symbol, timeframe=timeframe.label)
            return 0

        log.info(
            "backfill_starting",
            symbol=symbol,
            timeframe=timeframe.label,
            from_date=str(effective_from),
            to_date=str(to_date),
        )

        bars = await self._fetcher.fetch(
            instrument_token=inst.instrument_token,
            trading_symbol=inst.trading_symbol,
            timeframe=timeframe,
            from_date=effective_from,
            to_date=to_date,
        )

        if not bars:
            log.warning("backfill_no_data", symbol=symbol)
            return 0

        # Write using CandleWriter (handles upsert)
        from sqlalchemy.ext.asyncio import async_sessionmaker
        writer = CandleWriter.__new__(CandleWriter)
        writer._session_factory = None
        writer._buffer = []
        writer._written_count = 0

        # Direct session write for backfill (no buffering needed)
        from app.publishers.postgres import _candle_to_row
        from sqlalchemy.dialects.postgresql import insert as pg_insert

        rows = [_candle_to_row(bar) for bar in bars]
        stmt = pg_insert(MarketBar).values(rows)
        stmt = stmt.on_conflict_do_update(
            index_elements=["symbol", "timeframe", "open_time"],
            set_={
                "high":        stmt.excluded.high,
                "low":         stmt.excluded.low,
                "close":       stmt.excluded.close,
                "volume":      stmt.excluded.volume,
                "updated_at":  stmt.excluded.updated_at,
            },
        )
        await self.db.execute(stmt)

        log.info("backfill_complete", symbol=symbol, bars=len(bars))
        return len(bars)

    async def get_bars(
        self,
        symbol: str,
        timeframe: Timeframe,
        from_date: date,
        to_date: date,
        limit: int = 1000,
    ) -> list[OHLCV]:
        """Fetch OHLCV bars from PostgreSQL (no live API call)."""
        from datetime import UTC, datetime

        from_dt = datetime.combine(from_date, datetime.min.time()).replace(tzinfo=UTC)
        to_dt   = datetime.combine(to_date,   datetime.max.time()).replace(tzinfo=UTC)

        result = await self.db.execute(
            select(MarketBar)
            .where(
                MarketBar.symbol == symbol,
                MarketBar.timeframe == timeframe.label,
                MarketBar.open_time >= from_dt,
                MarketBar.open_time <= to_dt,
            )
            .order_by(MarketBar.open_time.asc())
            .limit(limit)
        )
        rows = result.scalars().all()

        return [
            OHLCV(
                symbol=r.symbol,
                exchange=r.exchange or "NSE",
                timeframe=timeframe,
                open_time=int(r.open_time.timestamp()),
                close_time=int(r.open_time.timestamp()) + timeframe.value * 60,
                open=float(r.open),
                high=float(r.high),
                low=float(r.low),
                close=float(r.close),
                volume=int(r.volume),
                vwap=float(r.vwap or 0),
                trade_count=int(r.trade_count or 0),
                is_complete=True,
            )
            for r in rows
        ]

    async def _get_existing_dates(
        self,
        symbol: str,
        timeframe: Timeframe,
        from_date: date,
        to_date: date,
    ) -> set[date]:
        from datetime import UTC, datetime

        from_dt = datetime.combine(from_date, datetime.min.time()).replace(tzinfo=UTC)
        to_dt   = datetime.combine(to_date,   datetime.max.time()).replace(tzinfo=UTC)

        result = await self.db.execute(
            select(MarketBar.open_time)
            .where(
                MarketBar.symbol == symbol,
                MarketBar.timeframe == timeframe.label,
                MarketBar.open_time >= from_dt,
                MarketBar.open_time <= to_dt,
            )
        )
        return {row[0].date() for row in result.all()}
