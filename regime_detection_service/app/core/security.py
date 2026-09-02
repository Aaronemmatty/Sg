"""
JWT (RS256) bearer-token verification, matching auth_service's token format.

SECURITY FIX (CRITICAL — see AUTHENTICATION_REVIEW.md finding AUTH-01):
The previous version of this file returned an authenticated stub user
({"sub": "dev", ...}) whenever the public key file was missing — with NO
check for production environment. That meant a misconfigured or missing
Docker secret mount (a routine operational failure — wrong secret name,
volume not mounted, permission denied) silently turned into an
authentication bypass in production: every request was accepted as
authenticated with no verification at all, and `POST /recalculate` (a
mutating, resource-intensive endpoint) was reachable by anyone.

This version fails CLOSED in production — matching the pattern already
used correctly in 9 of the platform's other 11 services (e.g.
portfolio_management_service, execution_engine_service) — and only allows
the dev/standalone fallback when the environment is explicitly NOT
production.

Also fixed:
  - AUTH_REQUIRED=False no longer silently grants access platform-wide if
    accidentally left on in production; it now also requires non-production.
  - require_role() dependency added — this file previously had no
    role-based authorization at all, meaning every endpoint that opted in
    was effectively "any authenticated user" with no distinction. Equivalent
    in spirit to risk_engine_service's gate, but WITHOUT the platform-wide
    "admin" skeleton-key bypass found there (see AUTHORIZATION_REVIEW.md
    finding AUTHZ-01) — only the exact required role passes.
  - Exception detail no longer echoes the raw PyJWTError text back to the
    caller (information disclosure) — logged server-side instead.
  - `roles` claim is validated to be a list of strings before use.
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
            # AUTH_REQUIRED=False must never be honored in production,
            # regardless of how it got set (config drift, bad default,
            # accidental env var). Fail closed rather than silently
            # granting anonymous access.
            logger.error("auth_required_false_in_production_blocked")
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Auth verification misconfigured",
            )
        return {"sub": "anonymous", "tenant_id": settings.DEFAULT_TENANT_ID, "roles": []}

    public_key = _load_public_key()
    if public_key is None:
        if production:
            # FAIL CLOSED in production — this is the critical fix.
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
        # Do not echo str(exc) to the client — avoid leaking library/version
        # fingerprinting or internal claim details. Log server-side instead.
        logger.info("jwt_verification_failed", extra={"reason": type(exc).__name__})
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token") from exc

    roles = payload.get("roles", [])
    if not isinstance(roles, list) or not all(isinstance(r, str) for r in roles):
        roles = []
    payload["roles"] = roles
    return payload


def require_role(role: str):
    """Gate a route to callers whose token carries the exact `role` claim.

    Unlike risk_engine_service's current implementation, this does NOT grant
    a platform-wide bypass to any other role (e.g. "admin"). If a genuine
    admin-override capability is wanted, it should be an explicit, audited
    decision documented in AUTHORIZATION_REVIEW.md — not an incidental side
    effect of one service's dependency function.
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
