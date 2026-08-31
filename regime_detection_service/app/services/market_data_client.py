"""
Historical OHLCV access for feature computation, backtesting, and warm-up windows.

Primary path: query `market_data.MarketBar` (already exists per the project brief) via the
shared `sg_db` ORM. Secondary path (used only if the DB read is empty/unavailable, e.g.
brand-new symbol not yet backfilled): call market_data_service's REST API directly.
"""
from __future__ import annotations

import logging
from datetime import datetime

import httpx
import pandas as pd
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings

logger = logging.getLogger(__name__)

try:
    from sg_db.models.market_data import MarketBar  # type: ignore
except ImportError:  # pragma: no cover - standalone/test fallback
    MarketBar = None  # resolved lazily; see _get_market_bar_model()


def _get_market_bar_model():
    if MarketBar is not None:
        return MarketBar
    raise RuntimeError(
        "sg_db.market_data.MarketBar is not importable in this environment. "
        "Wire up the real import in app/services/market_data_client.py, or use "
        "fetch_recent_bars_via_api() for standalone/dev runs."
    )


async def fetch_recent_bars_via_db(
    session: AsyncSession,
    symbol: str,
    exchange: str,
    timeframe: str,
    limit: int,
    end: datetime | None = None,
) -> pd.DataFrame:
    """Fetch the most recent `limit` bars up to `end` (or now) from MarketBar, ascending."""
    Bar = _get_market_bar_model()
    stmt = (
        select(Bar)
        .where(Bar.symbol == symbol, Bar.exchange == exchange, Bar.timeframe == timeframe)
        .order_by(Bar.timestamp.desc())
        .limit(limit)
    )
    if end is not None:
        stmt = stmt.where(Bar.timestamp <= end)

    result = await session.execute(stmt)
    rows = result.scalars().all()
    if not rows:
        return pd.DataFrame(columns=["timestamp", "open", "high", "low", "close", "volume"])

    df = pd.DataFrame(
        [
            {
                "timestamp": r.timestamp,
                "open": float(r.open),
                "high": float(r.high),
                "low": float(r.low),
                "close": float(r.close),
                "volume": int(r.volume),
            }
            for r in rows
        ]
    )
    return df.sort_values("timestamp").reset_index(drop=True)


async def fetch_range_bars_via_db(
    session: AsyncSession,
    symbol: str,
    exchange: str,
    timeframe: str,
    start: datetime,
    end: datetime,
) -> pd.DataFrame:
    """Fetch all bars in [start, end] ascending — used by the backtest service."""
    Bar = _get_market_bar_model()
    stmt = (
        select(Bar)
        .where(
            Bar.symbol == symbol,
            Bar.exchange == exchange,
            Bar.timeframe == timeframe,
            Bar.timestamp >= start,
            Bar.timestamp <= end,
        )
        .order_by(Bar.timestamp.asc())
    )
    result = await session.execute(stmt)
    rows = result.scalars().all()
    df = pd.DataFrame(
        [
            {
                "timestamp": r.timestamp,
                "open": float(r.open),
                "high": float(r.high),
                "low": float(r.low),
                "close": float(r.close),
                "volume": int(r.volume),
            }
            for r in rows
        ]
    )
    return df


async def fetch_recent_bars_via_api(
    settings: Settings, symbol: str, timeframe: str, limit: int
) -> pd.DataFrame:
    """Fallback: pull recent candles directly from market_data_service's REST API."""
    url = f"{settings.MARKET_DATA_SERVICE_URL}/api/v1/candles/{symbol}"
    params = {"timeframe": timeframe, "limit": limit}
    async with httpx.AsyncClient(timeout=5.0) as client:
        resp = await client.get(url, params=params)
        resp.raise_for_status()
        data = resp.json()
    df = pd.DataFrame(data.get("candles", data))
    if df.empty:
        return df
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    return df.sort_values("timestamp").reset_index(drop=True)


async def get_recent_bars(
    session: AsyncSession,
    settings: Settings,
    symbol: str,
    timeframe: str,
    limit: int,
    exchange: str | None = None,
) -> pd.DataFrame:
    """Preferred entry point: DB first, REST fallback if DB has insufficient history."""
    exchange = exchange or settings.PRIMARY_EXCHANGE
    try:
        df = await fetch_recent_bars_via_db(session, symbol, exchange, timeframe, limit)
    except Exception:  # noqa: BLE001
        logger.exception("DB bar fetch failed for %s:%s — trying REST fallback", symbol, timeframe)
        df = pd.DataFrame()

    if len(df) < settings.MIN_BARS_REQUIRED:
        try:
            df = await fetch_recent_bars_via_api(settings, symbol, timeframe, limit)
        except Exception:  # noqa: BLE001
            logger.exception("REST fallback also failed for %s:%s", symbol, timeframe)
    return df
