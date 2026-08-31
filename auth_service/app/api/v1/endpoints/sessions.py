"""Session and device management endpoints."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import AuthRequired
from app.db.session import get_db
from app.models.auth import UserDevice, UserSession
from app.schemas.auth import (
    DeviceInfo,
    OkResponse,
    RevokeSessionRequest,
    SessionInfo,
    SessionListResponse,
    TrustDeviceRequest,
)
from datetime import UTC, datetime

router = APIRouter(prefix="/sessions", tags=["Sessions & Devices"])


@router.get("", response_model=SessionListResponse, summary="List active sessions")
async def list_sessions(
    current: AuthRequired,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> SessionListResponse:
    result = await db.execute(
        select(UserSession).where(
            UserSession.user_id == current.user.id,
            UserSession.revoked_at.is_(None),
            UserSession.deleted_at.is_(None),
            UserSession.expires_at > datetime.now(UTC),
        )
    )
    sessions = result.scalars().all()

    current_jti = current.session_id  # session_id is actually session redis key
    items = [
        SessionInfo(
            session_id=s.id,
            device_name=None,
            device_type=None,
            ip_address=s.ip_address,
            created_at=s.created_at,
            last_active_at=s.last_active_at,
            is_current=(str(s.id) == current.session_id),
        )
        for s in sessions
    ]
    return SessionListResponse(sessions=items, total=len(items))


@router.delete("/{session_id}", response_model=OkResponse, summary="Revoke a specific session")
async def revoke_session(
    session_id: UUID,
    current: AuthRequired,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> OkResponse:
    result = await db.execute(
        select(UserSession).where(
            UserSession.id == session_id,
            UserSession.user_id == current.user.id,
            UserSession.deleted_at.is_(None),
        )
    )
    session = result.scalar_one_or_none()
    if not session:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found.")
    session.revoked_at = datetime.now(UTC)
    session.revoke_reason = "manual_revoke"
    return OkResponse(message="Session revoked.")


@router.get("/devices", response_model=list[DeviceInfo], tags=["Sessions & Devices"], summary="List tracked devices")
async def list_devices(
    current: AuthRequired,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> list[DeviceInfo]:
    result = await db.execute(
        select(UserDevice).where(
            UserDevice.user_id == current.user.id,
            UserDevice.deleted_at.is_(None),
        )
    )
    return [DeviceInfo.model_validate(d) for d in result.scalars().all()]


@router.post("/devices/trust", response_model=OkResponse, tags=["Sessions & Devices"], summary="Trust a device")
async def trust_device(
    body: TrustDeviceRequest,
    current: AuthRequired,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> OkResponse:
    device = await db.get(UserDevice, body.device_id)
    if not device or device.user_id != current.user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Device not found.")
    device.is_trusted = True
    device.trusted_at = datetime.now(UTC)
    return OkResponse(message="Device trusted.")
