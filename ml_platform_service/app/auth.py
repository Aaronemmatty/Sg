"""JWT auth — identical pattern to execution_engine_service (8008) and 8009."""
from __future__ import annotations

from pathlib import Path

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.config import settings
from app.core.logging import get_logger

log = get_logger(__name__)
_bearer = HTTPBearer(auto_error=False)
_DEV_STUB = {"sub": "dev-stub-user", "roles": ["analyst", "risk_officer", "ml_engineer"]}
_public_key_cache: str | None = None
_loaded = False


class CurrentUser:
    def __init__(self, username: str, roles: list[str]):
        self.username = username
        self.roles = roles

    def has_role(self, role: str) -> bool:
        return role in self.roles


def _load_key() -> str | None:
    raw = settings.auth_jwt_public_key_path.strip()
    if not raw:
        return None
    p = Path(raw)
    return p.read_text() if p.is_file() else None


def _get_key() -> str | None:
    global _public_key_cache, _loaded
    if not _loaded:
        _public_key_cache = _load_key()
        _loaded = True
    return _public_key_cache


async def get_current_user(
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> CurrentUser:
    key = _get_key()
    if key is None:
        if settings.is_production:
            raise HTTPException(status_code=503, detail="Auth unavailable")
        return CurrentUser(_DEV_STUB["sub"], _DEV_STUB["roles"])
    if creds is None:
        raise HTTPException(status_code=401, detail="Missing token")
    try:
        payload = jwt.decode(
            creds.credentials, key,
            algorithms=[settings.auth_jwt_algorithm],
            issuer=settings.auth_jwt_issuer,
            options={"require": ["exp", "sub"]},
        )
    except jwt.PyJWTError as e:
        raise HTTPException(status_code=401, detail=str(e))
    return CurrentUser(payload["sub"], payload.get("roles", []))


def require_role(role: str):
    async def _dep(user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
        if not user.has_role(role):
            raise HTTPException(status_code=403, detail=f"Requires role: {role}")
        return user
    return _dep
