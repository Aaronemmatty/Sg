from __future__ import annotations

from datetime import date, datetime, time, timezone

import httpx
import tenacity

from app.core.config import settings
from app.core.logging import log
from app.core.metrics import DATA_LOADER_FALLBACKS
from app.db.repository import BacktestRepository
from app.models.domain import OHLCVBar, Timeframe


class DataLoaderError(Exception):
    pass


class HistoricalDataLoader:
    """Sources historical OHLCV bars.

    Primary path: GET market_data_service /symbols/{symbol}/history with
    params start/end/interval, returning {"candles": [...]}.
    Assumed contract — isolated here exactly like market_data_client.py in
    portfolio_management_service (8009), so a real contract change only
    touches this file.

    Fallback path: bt_ohlcv_cache table in sg_db. Bars successfully fetched
    via REST are opportunistically cached so the fallback improves over time
    even though it starts out empty.
    """

    def __init__(self, repo: BacktestRepository, client: httpx.AsyncClient | None = None) -> None:
        self._repo = repo
        self._client = client or httpx.AsyncClient(
            base_url=settings.market_data_service_url,
            timeout=settings.http_client_timeout_seconds,
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def load(
        self, symbol: str, timeframe: Timeframe, start: date, end: date
    ) -> list[OHLCVBar]:
        start_dt = datetime.combine(start, time.min, tzinfo=timezone.utc)
        end_dt = datetime.combine(end, time.max, tzinfo=timezone.utc)

        try:
            bars = await self._fetch_rest(symbol, timeframe, start_dt, end_dt)
            if bars:
                await self._repo.cache_ohlcv(bars)
                return bars
            log.warning(
                "data_loader_rest_empty", symbol=symbol, timeframe=timeframe.value
            )
        except Exception as exc:  # noqa: BLE001
            log.warning(
                "data_loader_rest_failed",
                symbol=symbol,
                timeframe=timeframe.value,
                error=str(exc),
            )

        DATA_LOADER_FALLBACKS.inc()
        cached = await self._repo.get_cached_ohlcv(symbol, timeframe, start_dt, end_dt)
        if not cached:
            raise DataLoaderError(
                f"No historical data available for {symbol} [{timeframe.value}] "
                f"{start} → {end} from REST or DB cache"
            )
        return cached

    @tenacity.retry(
        stop=tenacity.stop_after_attempt(3),
        wait=tenacity.wait_exponential(multiplier=0.5, max=4),
        retry=tenacity.retry_if_exception_type(httpx.HTTPError),
        reraise=True,
    )
    async def _fetch_rest(
        self, symbol: str, timeframe: Timeframe, start_dt: datetime, end_dt: datetime
    ) -> list[OHLCVBar]:
        resp = await self._client.get(
            f"/symbols/{symbol}/history",
            params={
                "start": start_dt.isoformat(),
                "end": end_dt.isoformat(),
                "interval": timeframe.value,
            },
        )
        resp.raise_for_status()
        payload = resp.json()
        raw_candles = payload.get("candles") or payload.get("prices") or []

        bars: list[OHLCVBar] = []
        for c in raw_candles:
            if isinstance(c, dict):
                ts_raw = c.get("ts") or c.get("timestamp") or c.get("date")
                ts = datetime.fromisoformat(ts_raw) if isinstance(ts_raw, str) else ts_raw
                bars.append(
                    OHLCVBar(
                        symbol=symbol,
                        timeframe=timeframe,
                        ts=ts,
                        open=float(c.get("open", c.get("close", 0.0))),
                        high=float(c.get("high", c.get("close", 0.0))),
                        low=float(c.get("low", c.get("close", 0.0))),
                        close=float(c["close"]),
                        volume=float(c.get("volume", 0.0)),
                    )
                )
            else:
                # Degenerate {"prices": [floats]} shape — synthesize a daily index.
                bars.append(
                    OHLCVBar(
                        symbol=symbol,
                        timeframe=timeframe,
                        ts=start_dt,
                        open=float(c),
                        high=float(c),
                        low=float(c),
                        close=float(c),
                        volume=0.0,
                    )
                )
        return bars

    async def load_benchmark(
        self, benchmark_symbol: str, timeframe: Timeframe, start: date, end: date
    ) -> list[OHLCVBar]:
        try:
            return await self.load(benchmark_symbol, timeframe, start, end)
        except DataLoaderError:
            log.warning("benchmark_data_unavailable", symbol=benchmark_symbol)
            return []
