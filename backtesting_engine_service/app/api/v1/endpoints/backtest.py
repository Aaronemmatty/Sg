from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.deps import get_job_manager, get_repository
from app.auth import get_current_user
from app.db.repository import BacktestRepository
from app.models.domain import (
    BacktestMode,
    BacktestResultBundle,
    BacktestRun,
    BacktestRunRequest,
    SimulatedTrade,
)
from app.services.job_manager import JobManager
from app.services.result_bundle import build_result_bundle

router = APIRouter(prefix="/backtest", tags=["backtest"])


@router.post("/run", status_code=status.HTTP_202_ACCEPTED)
async def run_backtest(
    request: BacktestRunRequest,
    job_manager: JobManager = Depends(get_job_manager),
    user: dict[str, Any] = Depends(get_current_user),
) -> dict:
    if request.mode == BacktestMode.WALK_FORWARD and request.walk_forward is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="walk_forward config is required when mode=walk_forward",
        )
    if request.mode == BacktestMode.MONTE_CARLO and request.monte_carlo is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="monte_carlo config is required when mode=monte_carlo",
        )

    run_id = await job_manager.submit(request)
    return {"id": str(run_id), "status": "PENDING"}


@router.get("")
async def list_backtests(
    limit: int = 50,
    offset: int = 0,
    repo: BacktestRepository = Depends(get_repository),
    user: dict[str, Any] = Depends(get_current_user),
) -> list[BacktestRun]:
    return await repo.list_runs(limit=limit, offset=offset)


@router.get("/{run_id}")
async def get_backtest(
    run_id: uuid.UUID,
    repo: BacktestRepository = Depends(get_repository),
    user: dict[str, Any] = Depends(get_current_user),
) -> BacktestRun:
    run = await repo.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Backtest run not found")
    return run


@router.post("/{run_id}/cancel")
async def cancel_backtest(
    run_id: uuid.UUID,
    job_manager: JobManager = Depends(get_job_manager),
    user: dict[str, Any] = Depends(get_current_user),
) -> dict:
    cancelled = await job_manager.cancel(run_id)
    if not cancelled:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Run not found or not currently active",
        )
    return {"id": str(run_id), "status": "CANCELLED"}


@router.get("/{run_id}/results")
async def get_results(
    run_id: uuid.UUID,
    repo: BacktestRepository = Depends(get_repository),
    user: dict[str, Any] = Depends(get_current_user),
) -> BacktestResultBundle:
    return await build_result_bundle(run_id, repo)


@router.get("/{run_id}/trades")
async def get_trades(
    run_id: uuid.UUID,
    repo: BacktestRepository = Depends(get_repository),
    user: dict[str, Any] = Depends(get_current_user),
) -> list[SimulatedTrade]:
    run = await repo.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Backtest run not found")
    return await repo.get_trades(run_id)


@router.get("/{run_id}/equity-curve")
async def get_equity_curve(
    run_id: uuid.UUID,
    repo: BacktestRepository = Depends(get_repository),
    user: dict[str, Any] = Depends(get_current_user),
):
    run = await repo.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Backtest run not found")
    return await repo.get_equity_curve(run_id)


@router.get("/{run_id}/walk-forward")
async def get_walk_forward_result(
    run_id: uuid.UUID,
    repo: BacktestRepository = Depends(get_repository),
    user: dict[str, Any] = Depends(get_current_user),
):
    result = await repo.get_walk_forward(run_id)
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No walk-forward result for this run (wrong mode or not yet completed)",
        )
    return result


@router.get("/{run_id}/monte-carlo")
async def get_monte_carlo_result(
    run_id: uuid.UUID,
    repo: BacktestRepository = Depends(get_repository),
    user: dict[str, Any] = Depends(get_current_user),
):
    result = await repo.get_monte_carlo(run_id)
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No Monte Carlo result for this run (wrong mode or not yet completed)",
        )
    return result
