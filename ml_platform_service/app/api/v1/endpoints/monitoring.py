"""
Monitoring API endpoints.

GET /monitoring/accuracy          — rolling accuracy for all active models
GET /monitoring/drift             — drift summary across all symbols
GET /monitoring/health            — overall ML platform health
POST /monitoring/drift/compute    — trigger drift computation for a symbol
"""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Body, Depends, Query

from app.auth import CurrentUser, get_current_user
from app.core.logging import get_logger
from app.db import repository as repo
from app.models.domain import ModelType
from app.monitoring.drift_monitor import compute_drift_report, update_rolling_accuracy

log = get_logger(__name__)
router = APIRouter(prefix="/monitoring", tags=["monitoring"])


@router.get("/accuracy")
async def rolling_accuracy(
    symbol: str | None = Query(default=None),
    window: int = Query(default=50, le=500),
    _user: CurrentUser = Depends(get_current_user),
):
    """
    Rolling directional accuracy across all active champion models.
    Optionally filter by symbol.
    """
    champions = await repo.list_model_versions(
        symbol=symbol, status="champion", limit=200
    )
    results = []
    for v in champions:
        try:
            acc = await update_rolling_accuracy(
                v["symbol"], ModelType(v["model_type"]), window=window
            )
            results.append({
                "symbol": v["symbol"],
                "model_type": v["model_type"],
                "rolling_accuracy": round(acc, 4),
                "window": window,
                "version_id": str(v["version_id"]),
            })
        except Exception:
            log.warning("accuracy_compute_failed", symbol=v["symbol"])

    return {"accuracy": results, "count": len(results)}


@router.get("/drift")
async def drift_summary(
    symbol: str | None = Query(default=None),
    _user: CurrentUser = Depends(get_current_user),
):
    """
    Latest drift report for all active champion models.
    Flags any where drift_detected=True.
    """
    champions = await repo.list_model_versions(
        symbol=symbol, status="champion", limit=200
    )
    reports = []
    for v in champions:
        report = await repo.get_latest_drift_report(v["symbol"], v["model_type"])
        if report:
            reports.append({
                "symbol": v["symbol"],
                "model_type": v["model_type"],
                "drift_detected": report.get("drift_detected", False),
                "overall_psi": report.get("overall_psi"),
                "computed_at": str(report.get("computed_at", "")),
            })

    alerts = [r for r in reports if r["drift_detected"]]
    return {
        "drift_reports": reports,
        "alerts": alerts,
        "alert_count": len(alerts),
    }


@router.post("/drift/compute")
async def trigger_drift_computation(
    symbol: Annotated[str, Body(embed=True)],
    model_type: Annotated[ModelType, Body(embed=True)] = ModelType.XGBOOST,
    _user: CurrentUser = Depends(get_current_user),
):
    """
    Manually trigger a drift computation for a symbol using current
    feature cache as the 'current' distribution.
    """
    from app.features.store import get_cached_feature_vector
    fv = await get_cached_feature_vector(symbol.upper())
    if fv is None:
        return {"error": f"No cached features for {symbol.upper()}"}

    # Build a minimal current feature array from the single cached vector
    current_dist = {
        fname: [getattr(fv, fname, 0.0)]
        for fname in fv.feature_names
    }
    report = await compute_drift_report(symbol.upper(), model_type, current_dist)
    return {
        "symbol": symbol.upper(),
        "model_type": model_type.value,
        "drift_detected": report.drift_detected,
        "overall_psi": report.overall_psi,
        "feature_count": len(report.feature_psi),
    }


@router.get("/health")
async def ml_platform_health(_user: CurrentUser = Depends(get_current_user)):
    """Overall ML platform health: champion counts, accuracy alerts, drift alerts."""
    champions = await repo.list_model_versions(status="champion", limit=500)
    total = len(champions)

    # Count symbols with at least one champion
    symbols_covered = len({v["symbol"] for v in champions})

    # Accuracy alerts (rolling < 48%)
    accuracy_alerts = []
    for v in champions:
        try:
            acc = await update_rolling_accuracy(v["symbol"], ModelType(v["model_type"]), window=50)
            if acc < 0.48:
                accuracy_alerts.append({
                    "symbol": v["symbol"],
                    "model_type": v["model_type"],
                    "accuracy": round(acc, 4),
                })
        except Exception:
            pass

    return {
        "status": "ok" if total > 0 else "no_models",
        "champion_models": total,
        "symbols_covered": symbols_covered,
        "accuracy_alerts": accuracy_alerts,
        "accuracy_alert_count": len(accuracy_alerts),
    }
