"""FastAPI dependencies — JWT extraction, RBAC, DB session injection."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.redis import is_jti_blacklisted
from app.core.security import decode_token
from app.db.session import get_db
from sg_db.models.identity import User

_bearer = HTTPBearer(auto_error=False)


class CurrentUser:
    """Container for the authenticated user context."""

    def __init__(
        self,
        user: User,
        roles: list[str],
        permissions: list[str],
        session_id: str,
        tenant_id: str,
    ) -> None:
        self.user = user
        self.roles = roles
        self.permissions = permissions
        self.session_id = session_id
        self.tenant_id = tenant_id

    def has_role(self, *roles: str) -> bool:
        return bool(set(roles) & set(self.roles))

    def has_permission(self, resource: str, action: str) -> bool:
        return f"{resource}:{action}" in self.permissions or "admin:*" in self.permissions


async def get_current_user(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> CurrentUser:
    credentials_exc = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Not authenticated",
        headers={"WWW-Authenticate": "Bearer"},
    )

    if not credentials:
        raise credentials_exc

    try:
        payload = decode_token(credentials.credentials)
    except JWTError:
        raise credentials_exc

    if payload.get("type") != "access":
        raise credentials_exc

    jti = payload.get("jti", "")
    if await is_jti_blacklisted(jti):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token revoked")

    user_id = payload.get("sub")
    if not user_id:
        raise credentials_exc

    user = await db.get(User, UUID(user_id))
    if not user or not user.is_active or user.deleted_at:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User inactive")

    return CurrentUser(
        user=user,
        roles=payload.get("roles", []),
        permissions=payload.get("perms", []),
        session_id=payload.get("sid", ""),
        tenant_id=payload.get("tid", ""),
    )


# Shorthand alias
AuthRequired = Annotated[CurrentUser, Depends(get_current_user)]


def require_roles(*roles: str):
    """Dependency factory: raises 403 if user lacks all listed roles."""

    async def _check(current: AuthRequired) -> CurrentUser:
        if not current.has_role(*roles):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Required role(s): {', '.join(roles)}",
            )
        return current

    return Depends(_check)


def require_permission(resource: str, action: str):
    """Dependency factory: raises 403 if user lacks the permission."""

    async def _check(current: AuthRequired) -> CurrentUser:
        if not current.has_permission(resource, action):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Missing permission: {resource}:{action}",
            )
        return current

    return Depends(_check)
