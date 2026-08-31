"""
JWT verification dependencies for broker_service.

Uses the shared JWT auth implementation from app.core.jwt_auth.
Provides get_current_user dependency and role guard functions.
"""
from __future__ import annotations

from app.core.config import get_settings
from app.core.jwt_auth import JWTAuthConfig, JWTAuthDependencies

settings = get_settings()

_auth = JWTAuthDependencies(JWTAuthConfig(
    public_key_path=settings.AUTH_JWT_PUBLIC_KEY_PATH,
    algorithm=settings.AUTH_JWT_ALGORITHM,
    issuer=settings.AUTH_JWT_ISSUER,
    is_production=settings.is_production,
    dev_stub_roles=["trader"],
))

get_current_user = _auth.get_current_user_dependency
require_role = _auth.require_role
require_any_role = _auth.require_any_role
