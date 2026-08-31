from __future__ import annotations

from pathlib import Path
from typing import Any

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.config import settings
from app.core.logging import log

_bearer_scheme = HTTPBearer(auto_error=False)

_public_key_cache: str | None = None
_DEV_STUB_USER: dict[str, Any] = {
    "sub": "dev-user",
    "roles": ["admin", "risk_officer", "trader"],
    "iss": settings.auth_jwt_issuer,
}


def _load_public_key() -> str | None:
    global _public_key_cache
    if _public_key_cache is not None:
        return _public_key_cache
    path = settings.auth_jwt_public_key_path
    if not path:
        return None
    key_path = Path(path)
    if not key_path.exists():
        log.error("jwt_public_key_missing", path=path)
        return None
    _public_key_cache = key_path.read_text()
    return _public_key_cache


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
) -> dict[str, Any]:
    public_key = _load_public_key()

    if public_key is None:
        if settings.env == "production":
            log.error("auth_fail_closed_production")
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Auth not configured",
            )
        return _DEV_STUB_USER

    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing credentials"
        )

    try:
        payload = jwt.decode(
            credentials.credentials,
            public_key,
            algorithms=[settings.auth_jwt_algorithm],
            issuer=settings.auth_jwt_issuer,
            options={"verify_aud": False},
        )
    except jwt.PyJWTError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail=f"Invalid token: {exc}"
        ) from exc

    return payload


def require_role(role: str):
    async def _dependency(user: dict[str, Any] = Depends(get_current_user)) -> dict[str, Any]:
        roles = user.get("roles", [])
        if role not in roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Requires role '{role}'",
            )
        return user

    return _dependency
