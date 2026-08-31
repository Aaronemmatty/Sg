"""
JWT verification — exact pattern from execution_engine_service (8008).

RS256 public key loaded from AUTH_JWT_PUBLIC_KEY_PATH (from auth_service / 8001).
Falls back to a dev stub user in non-production when key file is absent.
Fails closed (503) in production if key is missing.
"""
from __future__ import annotations

from pathlib import Path

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.config import settings
from app.core.logging import get_logger

log = get_logger(__name__)

_bearer = HTTPBearer(auto_error=False)
_DEV_STUB_USER = {"sub": "dev-stub-user", "roles": ["analyst", "risk_officer"]}


class CurrentUser:
    def __init__(self, username: str, roles: list[str]) -> None:
        self.username = username
        self.roles = roles

    def has_role(self, role: str) -> bool:
        return role in self.roles


def _load_public_key() -> str | None:
    raw = settings.auth_jwt_public_key_path.strip()
    if not raw:
        return None
    path = Path(raw)
    return path.read_text() if path.is_file() else None


_public_key_cache: str | None = None
_public_key_loaded: bool = False


def _get_public_key() -> str | None:
    global _public_key_cache, _public_key_loaded
    if not _public_key_loaded:
        _public_key_cache = _load_public_key()
        _public_key_loaded = True
    return _public_key_cache


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> CurrentUser:
    public_key = _get_public_key()

    if public_key is None:
        if settings.is_production:
            log.error("auth_public_key_missing_in_production")
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Auth verification unavailable (fail-closed in production)",
            )
        log.warning("auth_dev_stub_user_active", env=settings.env)
        return CurrentUser(username=_DEV_STUB_USER["sub"], roles=_DEV_STUB_USER["roles"])

    if credentials is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing bearer token")

    try:
        payload = jwt.decode(
            credentials.credentials,
            public_key,
            algorithms=[settings.auth_jwt_algorithm],
            issuer=settings.auth_jwt_issuer,
            options={"require": ["exp", "sub"]},
        )
    except jwt.PyJWTError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=f"Invalid token: {exc}")

    return CurrentUser(username=payload["sub"], roles=payload.get("roles", []))


def require_role(role: str):
    async def _dep(user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
        if not user.has_role(role):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, detail=f"Requires role: {role}"
            )
        return user

    return _dep
