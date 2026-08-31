"""
Experiment Tracking API endpoints.

GET /experiments              — list MLflow experiments
GET /experiments/runs         — list runs (filterable by symbol / model_type)
GET /experiments/runs/{run_id}— single run detail
GET /experiments/compare      — compare metrics across runs
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from app.auth import CurrentUser, get_current_user
from app.core.config import settings
from app.core.logging import get_logger

log = get_logger(__name__)
router = APIRouter(prefix="/experiments", tags=["experiments"])


def _get_mlflow_client():
    try:
        import mlflow
        mlflow.set_tracking_uri(settings.mlflow_tracking_uri)
        return mlflow.tracking.MlflowClient()
    except Exception:
        return None


@router.get("/")
async def list_experiments(_user: CurrentUser = Depends(get_current_user)):
    """List all MLflow experiments."""
    client = _get_mlflow_client()
    if client is None:
        return {"experiments": [], "note": "MLflow unavailable"}
    try:
        experiments = client.search_experiments()
        return {
            "experiments": [
                {
                    "experiment_id": e.experiment_id,
                    "name": e.name,
                    "artifact_location": e.artifact_location,
                    "lifecycle_stage": e.lifecycle_stage,
                }
                for e in experiments
            ]
        }
    except Exception:
        log.warning("mlflow_list_experiments_failed")
        return {"experiments": [], "error": "MLflow query failed"}


@router.get("/runs")
async def list_runs(
    symbol: str | None = Query(default=None),
    model_type: str | None = Query(default=None),
    limit: int = Query(default=50, le=200),
    _user: CurrentUser = Depends(get_current_user),
):
    """List MLflow runs, optionally filtered by symbol and model_type tags."""
    client = _get_mlflow_client()
    if client is None:
        return {"runs": []}

    try:
        filter_parts = [f"tags.mlflow.runName LIKE '%'"]
        if symbol:
            filter_parts.append(f"tags.symbol = '{symbol.upper()}'")
        if model_type:
            filter_parts.append(f"tags.model_type = '{model_type}'")

        runs = client.search_runs(
            experiment_names=[settings.mlflow_experiment_name],
            filter_string=" AND ".join(filter_parts),
            max_results=limit,
            order_by=["start_time DESC"],
        )
        return {
            "runs": [
                {
                    "run_id": r.info.run_id,
                    "status": r.info.status,
                    "start_time": r.info.start_time,
                    "end_time": r.info.end_time,
                    "params": r.data.params,
                    "metrics": r.data.metrics,
                    "tags": r.data.tags,
                }
                for r in runs
            ],
            "count": len(runs),
        }
    except Exception:
        log.warning("mlflow_list_runs_failed")
        return {"runs": [], "error": "MLflow query failed"}


@router.get("/runs/{run_id}")
async def get_run(run_id: str, _user: CurrentUser = Depends(get_current_user)):
    """Get a single MLflow run by ID."""
    client = _get_mlflow_client()
    if client is None:
        raise HTTPException(status_code=503, detail="MLflow unavailable")
    try:
        run = client.get_run(run_id)
        return {
            "run_id": run.info.run_id,
            "status": run.info.status,
            "params": run.data.params,
            "metrics": run.data.metrics,
            "tags": run.data.tags,
            "artifact_uri": run.info.artifact_uri,
        }
    except Exception:
        raise HTTPException(status_code=404, detail=f"Run {run_id} not found")


@router.get("/compare")
async def compare_runs(
    symbol: str = Query(...),
    model_type: str = Query(...),
    metric: str = Query(default="val_metric"),
    limit: int = Query(default=10, le=50),
    _user: CurrentUser = Depends(get_current_user),
):
    """Compare metric values across recent runs for a symbol+model_type pair."""
    client = _get_mlflow_client()
    if client is None:
        return {"comparison": []}
    try:
        runs = client.search_runs(
            experiment_names=[settings.mlflow_experiment_name],
            filter_string=(
                f"tags.symbol = '{symbol.upper()}' "
                f"AND tags.model_type = '{model_type}'"
            ),
            max_results=limit,
            order_by=["start_time DESC"],
        )
        return {
            "symbol": symbol.upper(),
            "model_type": model_type,
            "metric": metric,
            "comparison": [
                {
                    "run_id": r.info.run_id,
                    "value": r.data.metrics.get(metric),
                    "start_time": r.info.start_time,
                }
                for r in runs
            ],
        }
    except Exception:
        return {"comparison": [], "error": "MLflow query failed"}
