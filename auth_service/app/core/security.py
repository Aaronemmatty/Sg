"""Security primitives — JWT, bcrypt, TOTP, token generation."""

from __future__ import annotations

import hashlib
import secrets
import string
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import pyotp
from jose import JWTError, jwt
from passlib.context import CryptContext

from app.core.config import get_settings

settings = get_settings()

import bcrypt

# ── Password ──────────────────────────────────────────────────────────────────

def hash_password(plain: str) -> str:
    return bcrypt.hashpw(plain.encode("utf-8")[:72], bcrypt.gensalt(12)).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode("utf-8")[:72], hashed.encode("utf-8"))
    except Exception:
        return False


def password_strength_ok(password: str) -> tuple[bool, str]:
    """Returns (ok, reason). Enforces NIST 800-63B guidelines."""
    if len(password) < 12:
        return False, "Password must be at least 12 characters."
    if len(password) > 128:
        return False, "Password must not exceed 128 characters."
    has_upper = any(c.isupper() for c in password)
    has_lower = any(c.islower() for c in password)
    has_digit = any(c.isdigit() for c in password)
    has_special = any(c in string.punctuation for c in password)
    if not (has_upper and has_lower and has_digit and has_special):
        return False, "Password must contain uppercase, lowercase, digit, and special character."
    return True, ""


# ── JWT ───────────────────────────────────────────────────────────────────────

def _now() -> datetime:
    return datetime.now(UTC)


def create_access_token(
    *,
    sub: str,
    tenant_id: str,
    roles: list[str],
    permissions: list[str],
    session_id: str,
    jti: str | None = None,
    extra: dict[str, Any] | None = None,
) -> str:
    jti = jti or secrets.token_urlsafe(32)
    now = _now()
    payload: dict[str, Any] = {
        "sub": sub,
        "tid": tenant_id,
        "roles": roles,
        "perms": permissions,
        "sid": session_id,
        "jti": jti,
        "iat": now,
        "nbf": now,
        "exp": now + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES),
        "type": "access",
    }
    if extra:
        payload.update(extra)
    return jwt.encode(payload, settings.JWT_PRIVATE_KEY, algorithm=settings.JWT_ALGORITHM)


def create_refresh_token(
    *,
    sub: str,
    tenant_id: str,
    session_id: str,
    jti: str | None = None,
) -> str:
    jti = jti or secrets.token_urlsafe(32)
    now = _now()
    payload: dict[str, Any] = {
        "sub": sub,
        "tid": tenant_id,
        "sid": session_id,
        "jti": jti,
        "iat": now,
        "nbf": now,
        "exp": now + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS),
        "type": "refresh",
    }
    return jwt.encode(payload, settings.JWT_PRIVATE_KEY, algorithm=settings.JWT_ALGORITHM)


def decode_token(token: str) -> dict[str, Any]:
    """Raises JWTError on any validation failure."""
    return jwt.decode(
        token,
        settings.JWT_PUBLIC_KEY,
        algorithms=[settings.JWT_ALGORITHM],
        options={"verify_exp": True, "verify_nbf": True},
    )


# ── TOTP / MFA ────────────────────────────────────────────────────────────────

def generate_totp_secret() -> str:
    return pyotp.random_base32()


def totp_provisioning_uri(secret: str, email: str) -> str:
    totp = pyotp.TOTP(secret, interval=settings.MFA_OTP_PERIOD)
    return totp.provisioning_uri(name=email, issuer_name="SG Trading")


def verify_totp(secret: str, code: str) -> bool:
    totp = pyotp.TOTP(secret, interval=settings.MFA_OTP_PERIOD)
    # Allow ±1 window for clock drift
    return totp.verify(code, valid_window=1)


def generate_backup_codes(n: int = 10) -> list[str]:
    """Generate one-time backup codes (plain). Caller must hash before storage."""
    return [secrets.token_hex(16).upper() for _ in range(n)]


def hash_backup_code(code: str) -> str:
    return hashlib.sha256(code.encode()).hexdigest()


# ── Misc tokens ───────────────────────────────────────────────────────────────

def generate_opaque_token(nbytes: int = 32) -> str:
    return secrets.token_urlsafe(nbytes)


def hash_api_key(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


def make_api_key() -> tuple[str, str, str]:
    """Returns (full_key, prefix, hash)."""
    raw = "sk_" + secrets.token_urlsafe(40)
    prefix = raw[:12]
    digest = hash_api_key(raw)
    return raw, prefix, digest
