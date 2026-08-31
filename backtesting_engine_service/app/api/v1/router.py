from __future__ import annotations

from fastapi import APIRouter

from app.api.v1.endpoints import backtest, health, reports

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(health.router)
api_router.include_router(backtest.router)
api_router.include_router(reports.router)
