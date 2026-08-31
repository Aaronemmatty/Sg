"""Request / Response schemas for the auth service."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field, field_validator


# ── Base ──────────────────────────────────────────────────────────────────────

class OkResponse(BaseModel):
    ok: bool = True
    message: str = "Success"


# ── Registration ──────────────────────────────────────────────────────────────

class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=12, max_length=128)
    display_name: str = Field(..., min_length=1, max_length=255)
    tenant_slug: str = Field(..., min_length=1, max_length=64)

    @field_validator("display_name")
    @classmethod
    def strip_name(cls, v: str) -> str:
        return v.strip()


class RegisterResponse(BaseModel):
    user_id: UUID
    email: str
    requires_email_verification: bool
    message: str


# ── Login ─────────────────────────────────────────────────────────────────────

class LoginRequest(BaseModel):
    email: EmailStr
    password: str
    tenant_slug: str
    device_name: Optional[str] = None


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int          # seconds
    session_id: str


class MfaChallengeResponse(BaseModel):
    challenge_id: str
    mfa_type: str            # totp | backup_code
    message: str = "MFA verification required"


# ── MFA ───────────────────────────────────────────────────────────────────────

class MfaVerifyRequest(BaseModel):
    challenge_id: str
    code: str = Field(..., min_length=6, max_length=8)


class MfaSetupResponse(BaseModel):
    secret: str
    provisioning_uri: str
    backup_codes: list[str]


class MfaEnableRequest(BaseModel):
    code: str = Field(..., min_length=6, max_length=6)


class MfaDisableRequest(BaseModel):
    code: str
    password: str


# ── Token lifecycle ───────────────────────────────────────────────────────────

class RefreshRequest(BaseModel):
    refresh_token: str


class LogoutRequest(BaseModel):
    refresh_token: str
    everywhere: bool = False


# ── Password ──────────────────────────────────────────────────────────────────

class ChangePasswordRequest(BaseModel):
    old_password: str
    new_password: str = Field(..., min_length=12, max_length=128)


class ForgotPasswordRequest(BaseModel):
    email: EmailStr
    tenant_slug: str


class ResetPasswordRequest(BaseModel):
    token: str
    new_password: str = Field(..., min_length=12, max_length=128)


# ── Email verification ────────────────────────────────────────────────────────

class VerifyEmailRequest(BaseModel):
    token: str


class ResendVerificationRequest(BaseModel):
    email: EmailStr
    tenant_slug: str


# ── Sessions ──────────────────────────────────────────────────────────────────

class SessionInfo(BaseModel):
    session_id: UUID
    device_name: Optional[str]
    device_type: Optional[str]
    ip_address: Optional[str]
    created_at: datetime
    last_active_at: Optional[datetime]
    is_current: bool

    model_config = {"from_attributes": True}


class SessionListResponse(BaseModel):
    sessions: list[SessionInfo]
    total: int


class RevokeSessionRequest(BaseModel):
    session_id: UUID


# ── Devices ───────────────────────────────────────────────────────────────────

class DeviceInfo(BaseModel):
    device_id: UUID
    device_name: Optional[str]
    device_type: Optional[str]
    os: Optional[str]
    browser: Optional[str]
    is_trusted: bool
    last_seen_at: Optional[datetime]
    login_count: int

    model_config = {"from_attributes": True}


class TrustDeviceRequest(BaseModel):
    device_id: UUID


# ── OAuth2 ────────────────────────────────────────────────────────────────────

class OAuthCallbackRequest(BaseModel):
    code: str
    state: str
    provider: str


# ── Profile / User ────────────────────────────────────────────────────────────

class UserProfile(BaseModel):
    user_id: UUID
    email: str
    display_name: str
    tenant_id: UUID
    roles: list[str]
    permissions: list[str]
    mfa_enabled: bool
    email_verified: bool
    created_at: datetime

    model_config = {"from_attributes": True}


# ── API Keys ──────────────────────────────────────────────────────────────────

class CreateApiKeyRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=128)
    scopes: list[str] = Field(default_factory=list)
    allowed_ips: Optional[list[str]] = None
    expires_days: Optional[int] = Field(None, ge=1, le=365)


class ApiKeyResponse(BaseModel):
    key_id: UUID
    name: str
    key: str          # shown ONCE
    prefix: str
    scopes: list[str]
    created_at: datetime


class ApiKeyInfo(BaseModel):
    key_id: UUID
    name: str
    prefix: str
    scopes: list[str]
    created_at: datetime
    last_used_at: Optional[datetime]
    expires_at: Optional[datetime]

    model_config = {"from_attributes": True}
