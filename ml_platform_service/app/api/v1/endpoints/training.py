"""
Training API endpoints.

POST /training/jobs              — submit a training job
GET  /training/jobs              — list jobs (filterable)
GET  /training/jobs/{job_id}     — single job detail
GET  /training/active            — currently running jobs
POST /training/retrain-all       — retrain all champion models (role-gated)
"""
from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Body, Depends, HTTPException, Query

from app.auth import CurrentUser, get_current_user, require_role
from app.core.logging import get_logger
from app.db import repository as repo
from app.models.domain import ModelType, TargetType, TrainingConfig
from app.training.dispatcher import TrainingDispatcher

log = get_logger(__name__)
router = APIRouter(prefix="/training", tags=["training"])


@router.post("/jobs", status_code=202)
async def submit_training_job(
    symbol: Annotated[str, Body(embed=True)],
    model_type: Annotated[ModelType, Body(embed=True)],
    target_type: Annotated[TargetType, Body(embed=True)] = TargetType.DIRECTION,
    n_trials: Annotated[int, Body(embed=True)] = 20,
    lookback_bars: Annotated[int, Body(embed=True)] = 500,
    sequence_length: Annotated[int, Body(embed=True)] = 20,
    hyperparams: Annotated[dict, Body(embed=True)] = {},
    _user: CurrentUser = Depends(require_role("ml_engineer")),
):
    """
    Submit an async training job. Returns job_id immediately.
    Use GET /training/jobs/{job_id} to poll status.
    """
    config = TrainingConfig(
        model_type=model_type,
        symbol=symbol.upper(),
        target_type=target_type,
        n_trials=n_trials,
        lookback_bars=lookback_bars,
        sequence_length=sequence_length,
        hyperparams=hyperparams,
    )
    result = await TrainingDispatcher.submit(config)
    return {
        "job_id": str(config.job_id),
        "status": result,
        "symbol": config.symbol,
        "model_type": model_type.value,
    }


@router.get("/jobs")
async def list_jobs(
    symbol: str | None = Query(default=None),
    model_type: str | None = Query(default=None),
    limit: int = Query(default=50, le=200),
    _user: CurrentUser = Depends(get_current_user),
):
    jobs = await repo.list_training_jobs(symbol=symbol, model_type=model_type, limit=limit)
    return {"jobs": jobs, "count": len(jobs)}


@router.get("/jobs/{job_id}")
async def get_job(job_id: uuid.UUID, _user: CurrentUser = Depends(get_current_user)):
    job = await repo.get_training_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")
    return job


@router.get("/active")
async def get_active_jobs(_user: CurrentUser = Depends(get_current_user)):
    """List currently running training jobs (in-memory — cleared on restart)."""
    return {"active_jobs": TrainingDispatcher.active_jobs()}


@router.post("/retrain-all", status_code=202)
async def retrain_all(
    target_type: Annotated[TargetType, Body(embed=True)] = TargetType.DIRECTION,
    n_trials: Annotated[int, Body(embed=True)] = 15,
    _user: CurrentUser = Depends(require_role("ml_engineer")),
):
    """
    Submit retraining jobs for ALL (symbol, model_type) pairs that have
    an active champion. Useful for scheduled after-market retraining.
    """
    versions = await repo.list_model_versions(status="champion", limit=200)
    submitted = []
    skipped = []
    for v in versions:
        config = TrainingConfig(
            model_type=ModelType(v["model_type"]),
            symbol=v["symbol"],
            target_type=target_type,
            n_trials=n_trials,
        )
        result = await TrainingDispatcher.submit(config)
        if result == "started":
            submitted.append(f"{v['symbol']}:{v['model_type']}")
        else:
            skipped.append(f"{v['symbol']}:{v['model_type']}")

    return {"submitted": submitted, "skipped": skipped}
