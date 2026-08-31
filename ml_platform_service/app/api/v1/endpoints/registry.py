"""
Model Registry API endpoints.

GET  /registry/models              — list all model versions
GET  /registry/models/{version_id} — single model version
GET  /registry/champions           — current champion per (symbol, model_type)
POST /registry/promote/{version_id}— manually promote a challenger
POST /registry/retire/{version_id} — retire a model version
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query

from app.auth import CurrentUser, get_current_user, require_role
from app.db import repository as repo
from app.models.domain import ModelType

router = APIRouter(prefix="/registry", tags=["registry"])


@router.get("/models")
async def list_models(
    symbol: str | None = Query(default=None),
    model_type: str | None = Query(default=None),
    status: str | None = Query(default=None),
    limit: int = Query(default=50, le=200),
    _user: CurrentUser = Depends(get_current_user),
):
    versions = await repo.list_model_versions(
        symbol=symbol, model_type=model_type, status=status, limit=limit
    )
    return {"models": versions, "count": len(versions)}


@router.get("/champions")
async def list_champions(_user: CurrentUser = Depends(get_current_user)):
    """Return the current champion model for every (symbol, model_type) pair."""
    versions = await repo.list_model_versions(status="champion", limit=500)
    # Group by symbol
    by_symbol: dict[str, list] = {}
    for v in versions:
        by_symbol.setdefault(v["symbol"], []).append(v)
    return {"champions": by_symbol, "total": len(versions)}


@router.get("/models/{version_id}")
async def get_model_version(
    version_id: uuid.UUID,
    _user: CurrentUser = Depends(get_current_user),
):
    versions = await repo.list_model_versions(limit=1)
    async with __import__("app.db.session", fromlist=["pool"]).pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM ml_model_versions WHERE version_id = $1", version_id
        )
    if not row:
        raise HTTPException(status_code=404, detail="Model version not found")
    return dict(row)


@router.post("/promote/{version_id}", status_code=200)
async def promote_model(
    version_id: uuid.UUID,
    _user: CurrentUser = Depends(require_role("ml_engineer")),
):
    """Manually promote a model version to champion status."""
    await repo.promote_model(version_id)
    return {"promoted": str(version_id)}


@router.post("/retire/{version_id}", status_code=200)
async def retire_model(
    version_id: uuid.UUID,
    _user: CurrentUser = Depends(require_role("ml_engineer")),
):
    """Retire a model version."""
    await repo.retire_model(version_id)
    return {"retired": str(version_id)}
