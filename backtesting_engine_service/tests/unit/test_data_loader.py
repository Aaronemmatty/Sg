from __future__ import annotations

from datetime import date
from unittest.mock import AsyncMock

import httpx
import pytest

from app.db.repository import BacktestRepository
from app.models.domain import OHLCVBar, Timeframe
from app.services.data_loader import DataLoaderError, HistoricalDataLoader


def _mock_response(payload: dict, status: int = 200) -> httpx.Response:
    request = httpx.Request("GET", "http://market_data_service/symbols/TEST/history")
    return httpx.Response(status_code=status, json=payload, request=request)


@pytest.mark.asyncio
async def test_load_uses_rest_and_caches_on_success():
    repo = AsyncMock(spec=BacktestRepository)
    client = AsyncMock(spec=httpx.AsyncClient)
    client.get.return_value = _mock_response(
        {
            "candles": [
                {"ts": "2024-01-01T00:00:00+00:00", "open": 100, "high": 101, "low": 99, "close": 100.5, "volume": 1000},
                {"ts": "2024-01-02T00:00:00+00:00", "open": 100.5, "high": 102, "low": 100, "close": 101.5, "volume": 1200},
            ]
        }
    )

    loader = HistoricalDataLoader(repo, client=client)
    bars = await loader.load("TEST", Timeframe.D1, date(2024, 1, 1), date(2024, 1, 2))

    assert len(bars) == 2
    assert bars[0].close == 100.5
    repo.cache_ohlcv.assert_awaited_once()


@pytest.mark.asyncio
async def test_load_falls_back_to_db_cache_when_rest_fails():
    repo = AsyncMock(spec=BacktestRepository)
    cached_bar = OHLCVBar(
        symbol="TEST",
        timeframe=Timeframe.D1,
        ts="2024-01-01T00:00:00+00:00",
        open=99.0,
        high=100.0,
        low=98.0,
        close=99.5,
        volume=500.0,
    )
    repo.get_cached_ohlcv.return_value = [cached_bar]

    client = AsyncMock(spec=httpx.AsyncClient)
    client.get.side_effect = httpx.ConnectError("connection refused")

    loader = HistoricalDataLoader(repo, client=client)
    bars = await loader.load("TEST", Timeframe.D1, date(2024, 1, 1), date(2024, 1, 2))

    assert bars == [cached_bar]
    repo.get_cached_ohlcv.assert_awaited_once()


@pytest.mark.asyncio
async def test_load_raises_when_both_rest_and_cache_empty():
    repo = AsyncMock(spec=BacktestRepository)
    repo.get_cached_ohlcv.return_value = []

    client = AsyncMock(spec=httpx.AsyncClient)
    client.get.side_effect = httpx.ConnectError("connection refused")

    loader = HistoricalDataLoader(repo, client=client)
    with pytest.raises(DataLoaderError):
        await loader.load("TEST", Timeframe.D1, date(2024, 1, 1), date(2024, 1, 2))


@pytest.mark.asyncio
async def test_load_benchmark_degrades_to_empty_list_on_failure():
    repo = AsyncMock(spec=BacktestRepository)
    repo.get_cached_ohlcv.return_value = []
    client = AsyncMock(spec=httpx.AsyncClient)
    client.get.side_effect = httpx.ConnectError("connection refused")

    loader = HistoricalDataLoader(repo, client=client)
    bars = await loader.load_benchmark("NIFTY50", Timeframe.D1, date(2024, 1, 1), date(2024, 1, 2))
    assert bars == []
