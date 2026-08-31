from __future__ import annotations

import uuid

from fastapi import HTTPException, status

from app.db.repository import BacktestRepository
from app.models.domain import BacktestMode, BacktestResultBundle


async def build_result_bundle(run_id: uuid.UUID, repo: BacktestRepository) -> BacktestResultBundle:
    run = await repo.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Backtest run not found")

    performance = await repo.get_performance(run_id)
    equity_curve = await repo.get_equity_curve(run_id)
    trades = await repo.get_trades(run_id)
    walk_forward = (
        await repo.get_walk_forward(run_id) if run.mode == BacktestMode.WALK_FORWARD else None
    )
    monte_carlo = (
        await repo.get_monte_carlo(run_id) if run.mode == BacktestMode.MONTE_CARLO else None
    )

    return BacktestResultBundle(
        run=run,
        performance=performance,
        equity_curve=equity_curve,
        trades=trades,
        walk_forward=walk_forward,
        monte_carlo=monte_carlo,
    )
