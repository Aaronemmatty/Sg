from __future__ import annotations

import uuid
from datetime import date, datetime, timezone

import pytest

from app.models.domain import (
    BacktestConfig,
    BacktestMode,
    BacktestRun,
    BacktestStatus,
    StrategyRef,
    StrategySourceType,
    Timeframe,
)


def _sample_config() -> BacktestConfig:
    return BacktestConfig(
        name="API Test Strategy",
        symbols=["RELIANCE"],
        primary_timeframe=Timeframe.D1,
        start_date=date(2024, 1, 1),
        end_date=date(2024, 6, 1),
        initial_capital_inr=500_000.0,
        strategy=StrategyRef(
            source=StrategySourceType.INLINE,
            inline_rules={
                "indicators": {"fast": {"type": "sma", "period": 5}, "slow": {"type": "sma", "period": 20}},
                "entry_long": {"left": "fast", "op": "cross_above", "right": "slow"},
                "exit_long": {"left": "fast", "op": "cross_below", "right": "slow"},
            },
        ),
    )


def _sample_run(run_id: uuid.UUID, status: BacktestStatus = BacktestStatus.COMPLETED) -> BacktestRun:
    return BacktestRun(
        id=run_id,
        mode=BacktestMode.SINGLE,
        status=status,
        config=_sample_config(),
        created_at=datetime.now(timezone.utc),
    )


@pytest.mark.asyncio
async def test_run_backtest_returns_202_and_run_id(api):
    client, job_manager, _repo = api
    run_id = uuid.uuid4()
    job_manager.submit.return_value = run_id

    payload = {
        "mode": "single",
        "config": _sample_config().model_dump(mode="json"),
    }
    resp = await client.post("/api/v1/backtest/run", json=payload)

    assert resp.status_code == 202
    assert resp.json()["id"] == str(run_id)
    job_manager.submit.assert_awaited_once()


@pytest.mark.asyncio
async def test_run_backtest_requires_walk_forward_config_for_that_mode(api):
    client, _job_manager, _repo = api
    payload = {"mode": "walk_forward", "config": _sample_config().model_dump(mode="json")}
    resp = await client.post("/api/v1/backtest/run", json=payload)
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_get_backtest_returns_run(api):
    client, _job_manager, repo = api
    run_id = uuid.uuid4()
    repo.get_run.return_value = _sample_run(run_id)

    resp = await client.get(f"/api/v1/backtest/{run_id}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["id"] == str(run_id)
    assert body["status"] == "COMPLETED"


@pytest.mark.asyncio
async def test_get_backtest_404_when_missing(api):
    client, _job_manager, repo = api
    repo.get_run.return_value = None

    resp = await client.get(f"/api/v1/backtest/{uuid.uuid4()}")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_get_trades_returns_list(api):
    client, _job_manager, repo = api
    run_id = uuid.uuid4()
    repo.get_run.return_value = _sample_run(run_id)
    repo.get_trades.return_value = []

    resp = await client.get(f"/api/v1/backtest/{run_id}/trades")
    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.asyncio
async def test_get_equity_curve_404_for_unknown_run(api):
    client, _job_manager, repo = api
    repo.get_run.return_value = None

    resp = await client.get(f"/api/v1/backtest/{uuid.uuid4()}/equity-curve")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_cancel_backtest_not_found(api):
    client, job_manager, _repo = api
    job_manager.cancel.return_value = False

    resp = await client.post(f"/api/v1/backtest/{uuid.uuid4()}/cancel")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_cancel_backtest_success(api):
    client, job_manager, _repo = api
    job_manager.cancel.return_value = True
    run_id = uuid.uuid4()

    resp = await client.post(f"/api/v1/backtest/{run_id}/cancel")
    assert resp.status_code == 200
    assert resp.json()["status"] == "CANCELLED"


@pytest.mark.asyncio
async def test_walk_forward_result_404_when_absent(api):
    client, _job_manager, repo = api
    repo.get_walk_forward.return_value = None

    resp = await client.get(f"/api/v1/backtest/{uuid.uuid4()}/walk-forward")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_health_endpoint_reports_db_status(api):
    client, _job_manager, _repo = api
    resp = await client.get("/api/v1/health")
    assert resp.status_code == 200
    assert resp.json()["service"] == "backtesting_engine_service"
