"""
Performance endpoints.

GET /performance/{window}    — full PerformanceMetrics for a given window
GET /performance/summary     — quick multi-window summary (1d, 30d, 252d)
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from app.auth import CurrentUser, get_current_user
from app.core.logging import get_logger
from app.models.domain import PerformanceWindow
from app.services.performance_engine import compute_performance

log = get_logger(__name__)
router = APIRouter(prefix="/performance", tags=["performance"])

_VALID_WINDOWS = {w.value: w for w in PerformanceWindow}


@router.get("/summary")
async def performance_summary(_user: CurrentUser = Depends(get_current_user)):
    """Quick multi-window summary: 1d, 30d, and 252d performance."""
    results = {}
    for w in (PerformanceWindow.DAY_1, PerformanceWindow.DAYS_30, PerformanceWindow.DAYS_252):
        try:
            metrics = await compute_performance(w)
            results[w.value] = metrics.model_dump(mode="json")
        except Exception:
            log.warning("performance_summary_window_failed", window=w.value)
            results[w.value] = None
    return results


@router.get("/{window}")
async def get_performance(
    window: str,
    _user: CurrentUser = Depends(get_current_user),
):
    """
    Full PerformanceMetrics for a specific window.

    window: 1d | 7d | 30d | 90d | 252d | inception
    """
    w = _VALID_WINDOWS.get(window)
    if w is None:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid window '{window}'. Valid: {list(_VALID_WINDOWS.keys())}",
        )
    metrics = await compute_performance(w)
    return metrics.model_dump(mode="json")
