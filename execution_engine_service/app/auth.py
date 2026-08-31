"""
JWT verification, matching the pattern used by risk_engine_service (8007)
against auth_service (8001):
  - Real RS256 public key loaded from AUTH_JWT_PUBLIC_KEY_PATH
  - In non-production envs, if the key file is absent, fall back to a dev
    stub user (NEVER in production - fails closed)
  - Role-gated dependency for endpoints requiring 'risk_officer' (manual
    order cancellation override) vs any authenticated user (read-only).
"""
from __future__ import annotations

from pathlib import Path

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.config import settings
from app.logging_config import get_logger

log = get_logger(__name__)

_bearer = HTTPBearer(auto_error=False)

_DEV_STUB_USER = {"sub": "dev-stub-user", "roles": ["risk_officer"]}


class CurrentUser:
    def __init__(self, username: str, roles: list[str]):
        self.username = username
        self.roles = roles

    def has_role(self, role: str) -> bool:
        return role in self.roles


def _load_public_key() -> str | None:
    path = Path(settings.auth_jwt_public_key_path)
    if not path.exists():
        return None
    return path.read_text()


_public_key_cache: str | None = None
_public_key_loaded = False


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
    async def _dependency(user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
        if not user.has_role(role):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=f"Requires role: {role}")
        return user

    return _dependency
