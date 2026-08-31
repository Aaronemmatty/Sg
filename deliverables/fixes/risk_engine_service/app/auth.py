"""
JWT verification for risk_engine_service (8007).

SECURITY FIX (see AUTHORIZATION_REVIEW.md finding AUTHZ-01):
The previous require_role() implementation granted ANY caller holding an
"admin" role claim a bypass of every role check in this service:

    if not user.has_role(role) and not user.has_role("admin"):
        raise HTTPException(...)

No other service in the platform implements this pattern — it was unique
to risk_engine_service, undocumented, and meant "admin" silently functions
as a skeleton key across the platform's single most safety-critical
service (VaR, drawdown, kill switch, exposure limits). If this was
intentional, it needs to be an explicit, audited platform decision living
in AUTHORIZATION_REVIEW.md — not an incidental side effect of one
function. This fix removes it; reintroduce deliberately if actually wanted.

Also fixed:
  - Dev-stub fallback now requires `settings.env != "production"`
    explicitly (it already did, but the production check used a literal
    string comparison without a shared helper — kept here as-is since it
    was actually correct, just inconsistent in style vs. other services;
    a shared helper is provided in shared_security_lib/ to converge this).
  - Exception detail no longer echoes raw PyJWTError text to the client.
  - `roles`/`role` claim coercion now strictly validates list[str] rather
    than accepting arbitrary objects.
"""
from __future__ import annotations

import logging
from pathlib import Path

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.config import Settings, get_settings
from app.logging_setup import get_logger

log = get_logger(module="auth")

bearer_scheme = HTTPBearer(auto_error=False)


class CurrentUser:
    def __init__(self, sub: str, roles: list[str]) -> None:
        self.sub = sub
        self.roles = roles

    def has_role(self, role: str) -> bool:
        return role in self.roles


def _load_public_key(path: str) -> str | None:
    p = Path(path)
    if not p.exists():
        log.warning("jwt_public_key_missing", path=path)
        return None
    return p.read_text()


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    settings: Settings = Depends(get_settings),
) -> CurrentUser:
    if credentials is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing bearer token")

    public_key = _load_public_key(settings.auth_jwt_public_key_path)
    if public_key is None:
        if settings.env == "production":
            log.error("auth_public_key_missing_in_production")
            raise HTTPException(status_code=503, detail="Auth verification unavailable")
        log.warning("auth_dev_stub_user_active", env=settings.env)
        return CurrentUser(sub="dev-user", roles=["risk_officer"])

    try:
        payload = jwt.decode(
            credentials.credentials,
            public_key,
            algorithms=["RS256"],
            options={"require": ["exp", "sub"]},
        )
    except jwt.PyJWTError as exc:
        log.info("jwt_verification_failed", reason=type(exc).__name__)
        raise HTTPException(status_code=401, detail="Invalid token") from exc

    raw_roles = payload.get("roles") or payload.get("role") or []
    if isinstance(raw_roles, str):
        raw_roles = [raw_roles]
    roles = [r for r in raw_roles if isinstance(r, str)] if isinstance(raw_roles, list) else []

    return CurrentUser(sub=payload.get("sub", "unknown"), roles=roles)


def require_role(role: str):
    """Gate a route to callers whose token carries the exact `role` claim.

    NOTE: the previous "or user.has_role('admin')" platform-wide bypass has
    been removed (AUTHZ-01). If a genuine super-role is wanted for incident
    response (e.g. to clear the kill switch), make it an explicit second
    dependency — `Depends(require_role("risk_officer"))` OR a dedicated
    `Depends(require_any_role(["risk_officer", "platform_admin"]))` helper —
    rather than an implicit fallback inside every role check.
    """

    async def _dependency(user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
        if not user.has_role(role):
            raise HTTPException(status_code=403, detail=f"Requires role '{role}'")
        return user

    return _dependency


def require_any_role(roles: list[str]):
    """Explicit, auditable multi-role gate — use this instead of a silent
    'admin bypasses everything' pattern when more than one role should be
    able to call an endpoint (e.g. clearing the kill switch)."""

    async def _dependency(user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
        if not any(user.has_role(r) for r in roles):
            raise HTTPException(status_code=403, detail=f"Requires one of: {', '.join(roles)}")
        return user

    return _dependency
