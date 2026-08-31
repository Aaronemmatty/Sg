"""
PostgreSQL candle writer.

Persists completed OHLCV candles to sg_db's `market_bars` table.
Uses bulk UPSERT for efficiency — safe to call multiple times with the
same candle (idempotent on symbol + timeframe + open_time).
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Optional

from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.logging import get_logger
from app.core.types import OHLCV
from sg_db.models.market_data import MarketBar

log = get_logger(__name__)


class CandleWriter:
    """
    Batched OHLCV writer.

    Collects completed candles and flushes to PostgreSQL in batches
    to reduce round-trips during high-volume sessions.
    """

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        batch_size: int = 100,
        flush_interval_s: float = 5.0,
    ) -> None:
        self._session_factory = session_factory
        self._batch_size = batch_size
        self._flush_interval = flush_interval_s
        self._buffer: list[OHLCV] = []
        self._flush_task: Optional[asyncio.Task] = None
        self._written_count = 0

    async def start(self) -> None:
        self._flush_task = asyncio.create_task(
            self._periodic_flush(), name="candle-writer-flush"
        )
        log.info("candle_writer_started", batch_size=self._batch_size)

    async def stop(self) -> None:
        if self._flush_task:
            self._flush_task.cancel()
        await self._flush()   # drain remaining buffer
        log.info("candle_writer_stopped", total_written=self._written_count)

    async def write(self, candle: OHLCV) -> None:
        """Accept a completed candle for buffered writing."""
        self._buffer.append(candle)
        if len(self._buffer) >= self._batch_size:
            await self._flush()

    async def _periodic_flush(self) -> None:
        while True:
            await asyncio.sleep(self._flush_interval)
            if self._buffer:
                await self._flush()

    async def _flush(self) -> None:
        if not self._buffer:
            return

        batch = self._buffer[:]
        self._buffer.clear()

        try:
            async with self._session_factory() as session:
                await self._upsert_batch(session, batch)
                await session.commit()
            self._written_count += len(batch)
            log.debug("candles_flushed", count=len(batch), total=self._written_count)
        except Exception as exc:
            log.error("candle_flush_failed", count=len(batch), error=str(exc))
            # Re-buffer on failure (prepend to avoid data loss)
            self._buffer = batch + self._buffer

    async def _upsert_batch(self, session: AsyncSession, candles: list[OHLCV]) -> None:
        if not candles:
            return

        rows = [_candle_to_row(c) for c in candles]

        # PostgreSQL upsert — ON CONFLICT DO UPDATE (idempotent)
        stmt = pg_insert(MarketBar).values(rows)
        stmt = stmt.on_conflict_do_update(
            index_elements=["symbol", "exchange", "timeframe", "bar_ts"],
            set_={
                "high":        stmt.excluded.high,
                "low":         stmt.excluded.low,
                "close":       stmt.excluded.close,
                "volume":      stmt.excluded.volume,
                "vwap":        stmt.excluded.vwap,
                "trade_count": stmt.excluded.trade_count,
                "updated_at":  stmt.excluded.updated_at,
            },
        )
        await session.execute(stmt)

    @property
    def buffer_depth(self) -> int:
        return len(self._buffer)


def _candle_to_row(candle: OHLCV) -> dict:
    open_dt = datetime.fromtimestamp(candle.open_time, tz=UTC)
    return {
        "symbol":      candle.symbol,
        "exchange":    candle.exchange,
        "timeframe":   candle.timeframe.label,
        "bar_ts":   open_dt,
        "open":        candle.open,
        "high":        candle.high,
        "low":         candle.low,
        "close":       candle.close,
        "volume":      candle.volume,
        "vwap":        round(candle.vwap, 4),
        "trade_count": candle.trade_count,
        "updated_at":  datetime.now(UTC),
        "created_at":  datetime.now(UTC),
    }
