"""API key management endpoints."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import AuthRequired
from app.core.security import make_api_key
from app.db.session import get_db
from app.schemas.auth import ApiKeyInfo, ApiKeyResponse, CreateApiKeyRequest, OkResponse
from sg_db.models.identity import ApiKey

router = APIRouter(prefix="/api-keys", tags=["API Keys"])


@router.post("", response_model=ApiKeyResponse, status_code=status.HTTP_201_CREATED)
async def create_api_key(
    body: CreateApiKeyRequest,
    current: AuthRequired,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiKeyResponse:
    raw, prefix, key_hash = make_api_key()
    expires_at = (
        datetime.now(UTC) + timedelta(days=body.expires_days) if body.expires_days else None
    )
    key = ApiKey(
        tenant_id=current.user.tenant_id,
        user_id=current.user.id,
        name=body.name,
        key_prefix=prefix,
        key_hash=key_hash,
        scopes=body.scopes,
        allowed_ips=body.allowed_ips or [],
        expires_at=expires_at,
    )
    db.add(key)
    await db.flush()

    return ApiKeyResponse(
        key_id=key.id,
        name=key.name,
        key=raw,   # shown ONCE
        prefix=prefix,
        scopes=body.scopes,
        created_at=key.created_at,
    )


@router.get("", response_model=list[ApiKeyInfo])
async def list_api_keys(
    current: AuthRequired,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> list[ApiKeyInfo]:
    result = await db.execute(
        select(ApiKey).where(
            ApiKey.user_id == current.user.id,
            ApiKey.deleted_at.is_(None),
        )
    )
    return [ApiKeyInfo.model_validate(k) for k in result.scalars().all()]


@router.delete("/{key_id}", response_model=OkResponse)
async def revoke_api_key(
    key_id: UUID,
    current: AuthRequired,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> OkResponse:
    key = await db.get(ApiKey, key_id)
    if not key or key.user_id != current.user.id or key.deleted_at:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Key not found.")
    key.deleted_at = datetime.now(UTC)
    return OkResponse(message="API key revoked.")
