"""
JWT (RS256) bearer-token verification, matching auth_service's token format.

SECURITY FIX (CRITICAL — see AUTHENTICATION_REVIEW.md finding AUTH-01):
Identical bug and identical fix to regime_detection_service/app/core/security.py
(both files were byte-for-byte the same before this fix — copy/paste drift
from a shared origin). See that file's docstring for the full rationale.

Summary: the previous version fell back to an authenticated stub user
whenever the public key file was missing, with no production check — a
missing/misconfigured Docker secret mount silently became a full auth
bypass in production. This version fails closed in production and adds a
require_role() dependency that didn't exist before.
"""
from __future__ import annotations

import logging
from functools import lru_cache
from pathlib import Path
from typing import Any

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.config import get_settings

logger = logging.getLogger(__name__)
bearer_scheme = HTTPBearer(auto_error=False)


@lru_cache
def _load_public_key() -> str | None:
    settings = get_settings()
    path = Path(settings.JWT_PUBLIC_KEY_PATH)
    if not path.exists():
        logger.warning("jwt_public_key_missing", extra={"path": str(path)})
        return None
    return path.read_text()


from sg_security.env import is_production as _is_production


async def verify_token(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> dict:
    settings = get_settings()
    production = _is_production(settings)

    if not settings.AUTH_REQUIRED:
        if production:
            logger.error("auth_required_false_in_production_blocked")
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Auth verification misconfigured",
            )
        return {"sub": "anonymous", "tenant_id": settings.DEFAULT_TENANT_ID, "roles": []}

    public_key = _load_public_key()
    if public_key is None:
        if production:
            logger.error("auth_public_key_missing_in_production")
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Auth verification unavailable",
            )
        logger.warning("auth_dev_stub_user_active", extra={"env": getattr(settings, "env", "unknown")})
        return {"sub": "dev", "tenant_id": settings.DEFAULT_TENANT_ID, "roles": ["analyst", "risk_officer"]}

    if credentials is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing bearer token")

    try:
        payload = jwt.decode(
            credentials.credentials,
            public_key,
            algorithms=["RS256"],
            issuer=getattr(settings, "JWT_ISSUER", None) or None,
            options={"require": ["exp", "sub"]},
        )
    except Exception as exc:
        logger.info("jwt_verification_failed", extra={"reason": type(exc).__name__})
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token") from exc

    roles = payload.get("roles", [])
    if not isinstance(roles, list) or not all(isinstance(r, str) for r in roles):
        roles = []
    payload["roles"] = roles
    return payload


def require_role(role: str):
    """Gate a route to callers whose token carries the exact `role` claim.
    No platform-wide bypass for any other role — see regime_detection_service's
    sibling fix for why that pattern (found in risk_engine_service) is avoided.
    """

    async def _dependency(claims: dict = Depends(verify_token)) -> dict:
        roles = claims.get("roles", [])
        if role not in roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Requires role '{role}'",
            )
        return claims

    return _dependency
