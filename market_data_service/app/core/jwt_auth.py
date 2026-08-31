"""
JWT verification for market_data_service — hardened implementation matching
the platform auth pattern from auth_service (8001) and execution_engine_service (8008).

Uses RS256 with public key loaded from AUTH_JWT_PUBLIC_KEY_PATH.
In non-production envs, if the key file is absent, falls back to a dev
stub user (NEVER in production - fails closed with HTTP 503).
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from pathlib import Path

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

logger = logging.getLogger(__name__)

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
    algorithm: str = "RS256"
    issuer: str | None = None
    is_production: bool = True
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
