"""
Historical data ingestion.

Primary:  Kite Connect Historical API
Fallback: Yahoo Finance (symbol suffix .NS for NSE)

Kite historical API limits:
  - 1m data: max 60 days per request
  - 3m/5m data: max 100 days per request
  - 15m/30m/60m: max 400 days per request
  - Day: max 2000 days per request
"""

from __future__ import annotations

import asyncio
from datetime import date, datetime, timedelta
from typing import Optional
from zoneinfo import ZoneInfo

import pandas as pd
from kiteconnect import KiteConnect
from tenacity import (
    AsyncRetrying,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from app.core.config import get_settings
from app.core.logging import get_logger
from app.core.types import OHLCV, Timeframe

settings = get_settings()
log = get_logger(__name__)
IST = ZoneInfo(settings.MARKET_TIMEZONE)

# Kite timeframe labels
_KITE_TF_MAP: dict[int, str] = {
    1:   "minute",
    3:   "3minute",
    5:   "5minute",
    15:  "15minute",
    30:  "30minute",
    60:  "60minute",
    240: "60minute",  # Kite has no 4h — we aggregate from 1h
    375: "day",
}

# Kite max days per call per timeframe
_KITE_MAX_DAYS: dict[int, int] = {
    1: 60, 3: 100, 5: 100, 15: 400, 30: 400,
    60: 400, 240: 400, 375: 2000,
}

# Yahoo Finance suffix for NSE
_YAHOO_SUFFIX = ".NS"


class HistoricalFetcher:
    def __init__(self) -> None:
        pass

    async def _get_kite_client(self) -> KiteConnect | None:
        """Fetch a KiteConnect instance with the latest access token from Redis."""
        if settings.KITE_MODE != "live":
            return None
        import redis.asyncio as redis_lib
        access_token = settings.KITE_ACCESS_TOKEN
        try:
            r_b2 = redis_lib.from_url("redis://127.0.0.1:6379/2")
            cached_token = await r_b2.get("sg:kite:access_token")
            if cached_token:
                access_token = cached_token.decode() if isinstance(cached_token, bytes) else str(cached_token)
            await r_b2.aclose()
        except Exception as e:
            log.warning("kite_historical_redis_token_check_failed", error=str(e))
        return KiteConnect(api_key=settings.KITE_API_KEY, access_token=access_token)

    # ── Public API ────────────────────────────────────────────────────────────

    async def fetch(
        self,
        instrument_token: int,
        trading_symbol: str,
        timeframe: Timeframe,
        from_date: date,
        to_date: date,
        continuous: bool = False,
    ) -> list[OHLCV]:
        """
        Fetch historical OHLCV bars. Splits into chunks respecting Kite limits.
        Falls back to Yahoo Finance if Kite fails.
        """
        try:
            return await self._fetch_kite_chunked(
                instrument_token, trading_symbol, timeframe, from_date, to_date, continuous
            )
        except Exception as exc:
            log.warning(
                "kite_historical_failed_fallback_yahoo",
                symbol=trading_symbol,
                timeframe=timeframe.label,
                error=str(exc),
            )
            if settings.YAHOO_ENABLED:
                return await self._fetch_yahoo(trading_symbol, timeframe, from_date, to_date)
            raise

    # ── Kite Historical ───────────────────────────────────────────────────────

    async def _fetch_kite_chunked(
        self,
        instrument_token: int,
        trading_symbol: str,
        timeframe: Timeframe,
        from_date: date,
        to_date: date,
        continuous: bool,
    ) -> list[OHLCV]:
        kite_client = await self._get_kite_client()
        if not kite_client:
            raise RuntimeError("Kite not configured — running in mock mode")

        max_days = _KITE_MAX_DAYS[timeframe.value]
        chunks = _date_chunks(from_date, to_date, max_days)
        all_bars: list[OHLCV] = []

        for chunk_from, chunk_to in chunks:
            bars = await self._fetch_kite_single(
                kite_client, instrument_token, trading_symbol, timeframe,
                chunk_from, chunk_to, continuous,
            )
            all_bars.extend(bars)
            # Rate-limit: Kite allows ~3 req/sec historical
            await asyncio.sleep(0.35)

        log.info(
            "kite_historical_fetched",
            symbol=trading_symbol,
            timeframe=timeframe.label,
            bars=len(all_bars),
            from_date=str(from_date),
            to_date=str(to_date),
        )
        return all_bars

    async def _fetch_kite_single(
        self,
        kite_client: KiteConnect,
        instrument_token: int,
        trading_symbol: str,
        timeframe: Timeframe,
        from_date: date,
        to_date: date,
        continuous: bool,
    ) -> list[OHLCV]:
        kite_interval = _KITE_TF_MAP[timeframe.value]

        async for attempt in AsyncRetrying(
            stop=stop_after_attempt(3),
            wait=wait_exponential(multiplier=1, min=2, max=10),
            retry=retry_if_exception_type(Exception),
        ):
            with attempt:
                loop = asyncio.get_running_loop()
                raw = await loop.run_in_executor(
                    None,
                    lambda: kite_client.historical_data(
                        instrument_token=instrument_token,
                        from_date=str(from_date),
                        to_date=str(to_date),
                        interval=kite_interval,
                        continuous=continuous,
                    ),
                )

        return [_kite_bar_to_ohlcv(bar, trading_symbol, timeframe) for bar in raw]

    # ── Yahoo Finance Fallback ────────────────────────────────────────────────

    async def _fetch_yahoo(
        self,
        trading_symbol: str,
        timeframe: Timeframe,
        from_date: date,
        to_date: date,
    ) -> list[OHLCV]:
        import yfinance as yf

        yahoo_symbol = f"{trading_symbol}{_YAHOO_SUFFIX}"
        yahoo_interval = _timeframe_to_yahoo_interval(timeframe)

        if not yahoo_interval:
            log.warning("yahoo_no_interval_for_timeframe", timeframe=timeframe.label)
            return []

        loop = asyncio.get_running_loop()
        df: pd.DataFrame = await loop.run_in_executor(
            None,
            lambda: yf.download(
                yahoo_symbol,
                start=str(from_date),
                end=str(to_date + timedelta(days=1)),
                interval=yahoo_interval,
                auto_adjust=True,
                progress=False,
            ),
        )

        if df.empty:
            log.warning("yahoo_empty_result", symbol=yahoo_symbol)
            return []

        bars = []
        for ts, row in df.iterrows():
            try:
                dt = ts.to_pydatetime().replace(tzinfo=IST)
                epoch = int(dt.timestamp())
                bars.append(OHLCV(
                    symbol=f"NSE:{trading_symbol}",
                    exchange="NSE",
                    timeframe=timeframe,
                    open_time=epoch,
                    close_time=epoch + timeframe.value * 60,
                    open=float(row["Open"]),
                    high=float(row["High"]),
                    low=float(row["Low"]),
                    close=float(row["Close"]),
                    volume=int(row["Volume"]),
                    is_complete=True,
                ))
            except Exception:
                continue

        log.info(
            "yahoo_historical_fetched",
            symbol=yahoo_symbol,
            bars=len(bars),
            timeframe=timeframe.label,
        )
        return bars


# ── Helpers ───────────────────────────────────────────────────────────────────

def _date_chunks(
    from_date: date, to_date: date, max_days: int
) -> list[tuple[date, date]]:
    chunks = []
    current = from_date
    while current <= to_date:
        end = min(current + timedelta(days=max_days - 1), to_date)
        chunks.append((current, end))
        current = end + timedelta(days=1)
    return chunks


def _kite_bar_to_ohlcv(bar: dict, trading_symbol: str, tf: Timeframe) -> OHLCV:
    dt = bar["date"]
    if isinstance(dt, str):
        dt = datetime.fromisoformat(dt)
    epoch = int(dt.timestamp())
    return OHLCV(
        symbol=f"NSE:{trading_symbol}",
        exchange="NSE",
        timeframe=tf,
        open_time=epoch,
        close_time=epoch + tf.value * 60,
        open=float(bar["open"]),
        high=float(bar["high"]),
        low=float(bar["low"]),
        close=float(bar["close"]),
        volume=int(bar["volume"]),
        is_complete=True,
    )


def _timeframe_to_yahoo_interval(tf: Timeframe) -> Optional[str]:
    mapping = {
        1: "1m", 5: "5m", 15: "15m", 30: "30m",
        60: "1h", 375: "1d",
    }
    return mapping.get(tf.value)
