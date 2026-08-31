"""
shared_security_lib/jwt_auth.py — single hardened reference implementation
of JWT verification, intended to replace the 9 independently-drifted
copies currently living at:

  portfolio_management_service/app/auth.py
  risk_engine_service/app/auth.py
  execution_engine_service/app/auth.py
  ai_analyst_service/app/auth.py
  ml_platform_service/app/auth.py
  backtesting_engine_service/app/auth.py
  regime_detection_service/app/core/security.py
  signal_aggregation_service/app/core/security.py
  market_data_service / broker_service / strategy_service / execution_orchestrator_service
    (not yet inspected in this audit pass for their own auth dependency — check
     for the same pattern before assuming they're fine)

See AUTHENTICATION_REVIEW.md for the full rationale. Findings this
consolidation fixes, all of which existed in at least one of the 8 copies
above:

  AUTH-01 (CRITICAL): fail-OPEN to an authenticated stub user in production
    when the public key file is missing (regime_detection_service,
    signal_aggregation_service).
  AUTH-02 (HIGH): raw exception text echoed back to the client on a failed
    JWT decode (most copies) — minor info disclosure / fingerprinting.
  AUTH-03 (MEDIUM): two different production-environment checks in use
    (`settings.is_production` vs `settings.env == "production"`) — both
    happen to work today because every service's Settings uses the same
    Literal, but a future typo in either pattern fails differently. One
    shared helper removes the duplication.
  AUTH-04 (MEDIUM): inconsistent `roles` claim handling — some copies trust
    the claim's shape without validation, one accepts a singular `role`
    string field as a fallback. Centralizing this means a future schema
    change to auth_service's token shape only needs to be handled once.
  AUTH-05 (LOW): no support for key rotation — the public key is loaded
    once and cached for the process lifetime via a module-level/lru_cache
    global, so rotating auth_service's signing key requires restarting
    every downstream service, and there is no `kid`-based multi-key
    support to allow an overlap window during rotation. This reference
    implementation adds a TTL-based cache refresh so a key rotation
    propagates within `PUBLIC_KEY_CACHE_TTL_SECONDS` without a restart, and
    documents the remaining gap (true multi-key/JWKS support) as a v2 item.

This module is dependency-light (`pyjwt`, `fastapi`) and has no hard
dependency on any one service's own `app.core.config` — pass in whatever
your service already has via the `JWTAuthConfig` dataclass instead of
importing global settings, so it drops into any of the 12 services without
forcing a config refactor.

Usage in a service's app/auth.py:

    from shared_security_lib.jwt_auth import JWTAuthConfig, JWTAuthDependencies

    _auth = JWTAuthDependencies(JWTAuthConfig(
        public_key_path=settings.auth_jwt_public_key_path,
        algorithm=settings.auth_jwt_algorithm,   # must be "RS256"
        issuer=settings.auth_jwt_issuer,
        is_production=(settings.env == "production"),
        dev_stub_roles=["analyst", "risk_officer"],
    ))

    get_current_user = _auth.get_current_user
    require_role = _auth.require_role
    require_any_role = _auth.require_any_role
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from pathlib import Path

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

logger = logging.getLogger("shared_security_lib.jwt_auth")

PUBLIC_KEY_CACHE_TTL_SECONDS = 300  # re-read the key file at most every 5 minutes


class CurrentUser:
    __slots__ = ("sub", "roles", "tenant_id", "raw_claims")

    def __init__(self, sub: str, roles: list[str], tenant_id: str | None, raw_claims: dict) -> None:
        self.sub = sub
        self.roles = roles
        self.tenant_id = tenant_id
        self.raw_claims = raw_claims

    def has_role(self, role: str) -> bool:
        return role in self.roles

    def has_any_role(self, roles: list[str]) -> bool:
        return any(r in self.roles for r in roles)


@dataclass
class JWTAuthConfig:
    public_key_path: str
    algorithm: str = "RS256"          # pin explicitly — never read from the token itself
    issuer: str | None = None
    is_production: bool = True        # default to the safe side if the caller forgets to set this
    dev_stub_sub: str = "dev-stub-user"
    dev_stub_roles: list[str] = field(default_factory=lambda: ["analyst"])
    dev_stub_tenant_id: str | None = None
    required_claims: list[str] = field(default_factory=lambda: ["exp", "sub"])


class JWTAuthDependencies:
    def __init__(self, config: JWTAuthConfig) -> None:
        self._config = config
        self._bearer = HTTPBearer(auto_error=False)
        self._key_cache: str | None = None
        self._key_cache_loaded_at: float = 0.0

    def _load_public_key(self) -> str | None:
        now = time.monotonic()
        if self._key_cache is not None and (now - self._key_cache_loaded_at) < PUBLIC_KEY_CACHE_TTL_SECONDS:
            return self._key_cache

        raw = (self._config.public_key_path or "").strip()
        if not raw:
            self._key_cache, self._key_cache_loaded_at = None, now
            return None

        path = Path(raw)
        if not path.is_file():
            logger.warning("jwt_public_key_missing", extra={"path": raw})
            self._key_cache, self._key_cache_loaded_at = None, now
            return None

        self._key_cache = path.read_text()
        self._key_cache_loaded_at = now
        return self._key_cache

    def _build_get_current_user(self):
        bearer = self._bearer
        cfg = self._config
        load_key = self._load_public_key

        async def _get_current_user(
            credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
        ) -> CurrentUser:
            public_key = load_key()

            if public_key is None:
                if cfg.is_production:
                    # The fix for AUTH-01: never fall through to a stub
                    # user in production, regardless of why the key load
                    # failed.
                    logger.error("auth_public_key_missing_in_production")
                    raise HTTPException(
                        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                        detail="Auth verification unavailable",
                    )
                logger.warning("auth_dev_stub_user_active")
                return CurrentUser(
                    sub=cfg.dev_stub_sub,
                    roles=list(cfg.dev_stub_roles),
                    tenant_id=cfg.dev_stub_tenant_id,
                    raw_claims={},
                )

            if credentials is None:
                raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing bearer token")

            try:
                payload = jwt.decode(
                    credentials.credentials,
                    public_key,
                    algorithms=[cfg.algorithm],
                    issuer=cfg.issuer,
                    options={"require": cfg.required_claims},
                )
            except jwt.PyJWTError as exc:
                # The fix for AUTH-02: never echo str(exc) to the caller.
                logger.info("jwt_verification_failed", extra={"reason": type(exc).__name__})
                raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token") from exc

            roles_raw = payload.get("roles", payload.get("perms", []))
            roles = [r for r in roles_raw if isinstance(r, str)] if isinstance(roles_raw, list) else []

            return CurrentUser(
                sub=str(payload.get("sub", "unknown")),
                roles=roles,
                tenant_id=payload.get("tid"),
                raw_claims=payload,
            )

        return _get_current_user

    @property
    def get_current_user_dependency(self):
        if not hasattr(self, "_cached_dep"):
            self._cached_dep = self._build_get_current_user()
        return self._cached_dep

    def require_role(self, role: str):
        get_user = self.get_current_user_dependency

        async def _dependency(user: CurrentUser = Depends(get_user)) -> CurrentUser:
            if not user.has_role(role):
                raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=f"Requires role '{role}'")
            return user

        return _dependency

    def require_any_role(self, roles: list[str]):
        get_user = self.get_current_user_dependency

        async def _dependency(user: CurrentUser = Depends(get_user)) -> CurrentUser:
            if not user.has_any_role(roles):
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=f"Requires one of: {', '.join(roles)}",
                )
            return user

        return _dependency
