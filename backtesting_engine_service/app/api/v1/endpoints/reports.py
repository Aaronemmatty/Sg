from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import HTMLResponse

from app.api.deps import get_repository
from app.auth import get_current_user
from app.db.repository import BacktestRepository
from app.services.result_bundle import build_result_bundle
from app.services.reporting_service import (
    equity_curve_chart_data,
    generate_html_report,
    monte_carlo_fan_chart_data,
    trade_distribution_chart_data,
)

router = APIRouter(prefix="/backtest", tags=["reports"])


@router.get("/{run_id}/report", response_class=HTMLResponse)
async def get_html_report(
    run_id: uuid.UUID,
    repo: BacktestRepository = Depends(get_repository),
    user: dict[str, Any] = Depends(get_current_user),
) -> HTMLResponse:
    bundle = await build_result_bundle(run_id, repo)
    return HTMLResponse(content=generate_html_report(bundle))


@router.get("/{run_id}/chart/equity")
async def get_equity_chart(
    run_id: uuid.UUID,
    repo: BacktestRepository = Depends(get_repository),
    user: dict[str, Any] = Depends(get_current_user),
) -> dict:
    bundle = await build_result_bundle(run_id, repo)
    return equity_curve_chart_data(bundle)


@router.get("/{run_id}/chart/trades")
async def get_trade_distribution_chart(
    run_id: uuid.UUID,
    repo: BacktestRepository = Depends(get_repository),
    user: dict[str, Any] = Depends(get_current_user),
) -> dict:
    bundle = await build_result_bundle(run_id, repo)
    return trade_distribution_chart_data(bundle.trades)


@router.get("/{run_id}/chart/monte-carlo")
async def get_monte_carlo_chart(
    run_id: uuid.UUID,
    repo: BacktestRepository = Depends(get_repository),
    user: dict[str, Any] = Depends(get_current_user),
) -> dict:
    bundle = await build_result_bundle(run_id, repo)
    if not bundle.monte_carlo:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No Monte Carlo result for this run",
        )
    return monte_carlo_fan_chart_data(bundle)
