"""Auth service — all business logic for authentication flows."""

from __future__ import annotations

import hashlib
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from fastapi import Request
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.logging import get_logger
from app.core.redis import (
    clear_login_attempts,
    consume_mfa_challenge,
    consume_verification_token,
    delete_all_user_sessions,
    delete_session,
    get_login_attempts,
    get_session,
    increment_login_attempts,
    is_jti_blacklisted,
    is_locked_out,
    set_lockout,
    store_mfa_challenge,
    store_session,
    store_verification_token,
)
from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    generate_backup_codes,
    generate_opaque_token,
    generate_totp_secret,
    hash_backup_code,
    hash_password,
    password_strength_ok,
    totp_provisioning_uri,
    verify_password,
    verify_totp,
)
from app.models.auth import (
    EmailVerificationToken,
    MfaBackupCode,
    PasswordResetToken,
    UserDevice,
    UserSession,
)
from app.services.device import DeviceService
from app.services.email import EmailService
from sg_db.models.identity import ApiKey, Role, User
from sg_db.models.tenant import Tenant

settings = get_settings()
log = get_logger(__name__)


class AuthError(Exception):
    def __init__(self, message: str, code: str = "auth_error") -> None:
        self.message = message
        self.code = code
        super().__init__(message)


class AuthService:
    def __init__(self, db: AsyncSession, request: Request | None = None) -> None:
        self.db = db
        self.request = request
        self._email_svc = EmailService()
        self._device_svc = DeviceService(db)

    # ── Registration ──────────────────────────────────────────────────────────

    async def register(
        self,
        *,
        email: str,
        password: str,
        display_name: str,
        tenant_slug: str,
    ) -> User:
        tenant = await self._get_tenant(tenant_slug)

        ok, reason = password_strength_ok(password)
        if not ok:
            raise AuthError(reason, "weak_password")

        existing = await self.db.execute(
            select(User).where(
                User.tenant_id == tenant.id,
                User.email == email.lower(),
                User.deleted_at.is_(None),
            )
        )
        if existing.scalar_one_or_none():
            raise AuthError("Email already registered.", "email_exists")

        user = User(
            tenant_id=tenant.id,
            email=email.lower(),
            password_hash=hash_password(password),
            display_name=display_name,
            is_active=True,
            preferences={"email_verified": False},
        )
        self.db.add(user)
        await self.db.flush()

        if settings.EMAIL_VERIFICATION_REQUIRED:
            await self._send_verification_email(user)

        log.info("user_registered", user_id=str(user.id), tenant=tenant_slug)
        return user

    # ── Login ─────────────────────────────────────────────────────────────────

    async def login(
        self,
        *,
        email: str,
        password: str,
        tenant_slug: str,
        request: Request,
        device_name: str | None = None,
    ) -> dict[str, Any]:
        tenant = await self._get_tenant(tenant_slug)
        lockout_key = f"{tenant.id}:{email.lower()}"

        if await is_locked_out(lockout_key):
            raise AuthError(
                f"Account locked. Try again in {settings.LOCKOUT_DURATION_MINUTES} minutes.",
                "account_locked",
            )

        user = await self._get_user_by_email(email, tenant.id)
        if not user or not verify_password(password, user.password_hash):
            attempts = await increment_login_attempts(lockout_key)
            remaining = settings.MAX_LOGIN_ATTEMPTS - attempts
            if remaining <= 0:
                await set_lockout(lockout_key)
                raise AuthError("Too many failed attempts. Account locked.", "account_locked")
            raise AuthError(f"Invalid credentials. {remaining} attempts remaining.", "invalid_credentials")

        if not user.is_active:
            raise AuthError("Account disabled.", "account_disabled")

        if settings.EMAIL_VERIFICATION_REQUIRED:
            if not user.preferences.get("email_verified"):
                raise AuthError("Email not verified.", "email_not_verified")

        await clear_login_attempts(lockout_key)

        if user.mfa_enabled and user.mfa_secret:
            challenge_id = secrets.token_urlsafe(32)
            await store_mfa_challenge(challenge_id, str(user.id), ttl=300)
            log.info("mfa_challenge_issued", user_id=str(user.id))
            return {"mfa_required": True, "challenge_id": challenge_id, "mfa_type": "totp"}

        return await self._complete_login(user=user, tenant=tenant, request=request, device_name=device_name)

    async def verify_mfa_and_login(
        self,
        *,
        challenge_id: str,
        code: str,
        request: Request,
    ) -> dict[str, Any]:
        user_id = await consume_mfa_challenge(challenge_id)
        if not user_id:
            raise AuthError("MFA challenge expired or invalid.", "mfa_challenge_invalid")

        user = await self.db.get(User, UUID(user_id))
        if not user:
            raise AuthError("User not found.", "not_found")

        # Try TOTP first, then backup codes
        if verify_totp(user.mfa_secret, code):
            pass
        elif await self._verify_backup_code(user, code):
            pass
        else:
            raise AuthError("Invalid MFA code.", "mfa_invalid")

        tenant = await self.db.get(Tenant, user.tenant_id)
        return await self._complete_login(user=user, tenant=tenant, request=request)

    # ── Token lifecycle ───────────────────────────────────────────────────────

    async def refresh_tokens(self, *, refresh_token: str, request: Request) -> dict[str, Any]:
        try:
            payload = decode_token(refresh_token)
        except Exception:
            raise AuthError("Invalid refresh token.", "token_invalid")

        if payload.get("type") != "refresh":
            raise AuthError("Wrong token type.", "token_invalid")

        jti = payload["jti"]
        if await is_jti_blacklisted(jti):
            raise AuthError("Token revoked.", "token_revoked")

        user = await self.db.get(User, UUID(payload["sub"]))
        if not user or not user.is_active:
            raise AuthError("User not found or inactive.", "user_inactive")

        tenant = await self.db.get(Tenant, user.tenant_id)
        session = await self._get_session_by_jti(jti)
        if not session or session.revoked_at:
            raise AuthError("Session revoked.", "session_revoked")

        roles, permissions = await self._get_roles_permissions(user)
        new_jti = secrets.token_urlsafe(32)
        session_id = str(session.id)

        access_token = create_access_token(
            sub=str(user.id),
            tenant_id=str(user.tenant_id),
            roles=roles,
            permissions=permissions,
            session_id=session_id,
            jti=new_jti,
        )
        new_refresh = create_refresh_token(
            sub=str(user.id),
            tenant_id=str(user.tenant_id),
            session_id=session_id,
            jti=new_jti,
        )

        session.refresh_jti = new_jti
        session.last_active_at = datetime.now(UTC)

        log.info("tokens_refreshed", user_id=str(user.id), session_id=session_id)
        return {
            "access_token": access_token,
            "refresh_token": new_refresh,
            "token_type": "bearer",
            "expires_in": settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
            "session_id": session_id,
        }

    async def logout(
        self,
        *,
        refresh_token: str,
        user_id: UUID,
        everywhere: bool = False,
    ) -> None:
        try:
            payload = decode_token(refresh_token)
            jti = payload.get("jti", "")
            session = await self._get_session_by_jti(jti)
            if session:
                session.revoked_at = datetime.now(UTC)
                session.revoke_reason = "logout"
            await delete_session(payload.get("sid", ""))
        except Exception:
            pass

        if everywhere:
            await delete_all_user_sessions(str(user_id))

        log.info("user_logged_out", user_id=str(user_id), everywhere=everywhere)

    # ── MFA management ────────────────────────────────────────────────────────

    async def setup_mfa(self, *, user: User) -> dict[str, Any]:
        if user.mfa_enabled:
            raise AuthError("MFA already enabled.", "mfa_already_enabled")
        secret = generate_totp_secret()
        uri = totp_provisioning_uri(secret, user.email)
        backup_codes = generate_backup_codes(10)

        # Store secret temporarily in Redis until confirmed
        await store_verification_token(
            f"mfa_setup:{user.id}",
            {"secret": secret, "backup_codes": [hash_backup_code(c) for c in backup_codes]},
            ttl_seconds=600,
        )
        return {"secret": secret, "provisioning_uri": uri, "backup_codes": backup_codes}

    async def enable_mfa(self, *, user: User, code: str) -> None:
        data = await consume_verification_token(f"mfa_setup:{user.id}")
        if not data:
            raise AuthError("MFA setup expired. Start again.", "mfa_setup_expired")

        if not verify_totp(data["secret"], code):
            raise AuthError("Invalid TOTP code.", "mfa_invalid")

        user.mfa_enabled = True
        user.mfa_secret = data["secret"]

        for code_hash in data["backup_codes"]:
            self.db.add(MfaBackupCode(
                tenant_id=user.tenant_id,
                user_id=user.id,
                code_hash=code_hash,
            ))

        log.info("mfa_enabled", user_id=str(user.id))

    async def disable_mfa(self, *, user: User, code: str, password: str) -> None:
        if not verify_password(password, user.password_hash):
            raise AuthError("Invalid password.", "invalid_credentials")
        if not verify_totp(user.mfa_secret, code):
            raise AuthError("Invalid MFA code.", "mfa_invalid")

        user.mfa_enabled = False
        user.mfa_secret = None

        # Delete all backup codes
        result = await self.db.execute(
            select(MfaBackupCode).where(
                MfaBackupCode.user_id == user.id,
                MfaBackupCode.used_at.is_(None),
            )
        )
        for bc in result.scalars().all():
            await self.db.delete(bc)

        log.info("mfa_disabled", user_id=str(user.id))

    # ── Password ──────────────────────────────────────────────────────────────

    async def change_password(
        self, *, user: User, old_password: str, new_password: str
    ) -> None:
        if not verify_password(old_password, user.password_hash):
            raise AuthError("Current password incorrect.", "invalid_credentials")

        ok, reason = password_strength_ok(new_password)
        if not ok:
            raise AuthError(reason, "weak_password")

        user.password_hash = hash_password(new_password)
        await delete_all_user_sessions(str(user.id))
        log.info("password_changed", user_id=str(user.id))

    async def forgot_password(self, *, email: str, tenant_slug: str, request: Request) -> None:
        tenant = await self._get_tenant(tenant_slug)
        user = await self._get_user_by_email(email, tenant.id)
        if not user:
            return  # Silent — don't leak existence

        token = generate_opaque_token(32)
        token_hash = hashlib.sha256(token.encode()).hexdigest()
        expires = datetime.now(UTC) + timedelta(minutes=settings.PASSWORD_RESET_EXPIRE_MINUTES)

        self.db.add(PasswordResetToken(
            tenant_id=tenant.id,
            user_id=user.id,
            token_hash=token_hash,
            expires_at=expires,
            ip_requested=request.client.host if request.client else None,
        ))

        await self._email_svc.send_password_reset(email=user.email, token=token)
        log.info("password_reset_requested", user_id=str(user.id))

    async def reset_password(self, *, token: str, new_password: str) -> None:
        token_hash = hashlib.sha256(token.encode()).hexdigest()
        result = await self.db.execute(
            select(PasswordResetToken).where(
                PasswordResetToken.token_hash == token_hash,
                PasswordResetToken.used_at.is_(None),
                PasswordResetToken.expires_at > datetime.now(UTC),
            )
        )
        reset_record = result.scalar_one_or_none()
        if not reset_record:
            raise AuthError("Invalid or expired reset token.", "token_invalid")

        ok, reason = password_strength_ok(new_password)
        if not ok:
            raise AuthError(reason, "weak_password")

        user = await self.db.get(User, reset_record.user_id)
        user.password_hash = hash_password(new_password)
        reset_record.used_at = datetime.now(UTC)
        await delete_all_user_sessions(str(user.id))
        log.info("password_reset_completed", user_id=str(user.id))

    # ── Email verification ────────────────────────────────────────────────────

    async def verify_email(self, *, token: str) -> None:
        token_hash = hashlib.sha256(token.encode()).hexdigest()
        result = await self.db.execute(
            select(EmailVerificationToken).where(
                EmailVerificationToken.token_hash == token_hash,
                EmailVerificationToken.verified_at.is_(None),
                EmailVerificationToken.expires_at > datetime.now(UTC),
            )
        )
        record = result.scalar_one_or_none()
        if not record:
            raise AuthError("Invalid or expired verification link.", "token_invalid")

        user = await self.db.get(User, record.user_id)
        prefs = dict(user.preferences)
        prefs["email_verified"] = True
        user.preferences = prefs
        record.verified_at = datetime.now(UTC)
        log.info("email_verified", user_id=str(user.id))

    async def resend_verification(self, *, email: str, tenant_slug: str) -> None:
        tenant = await self._get_tenant(tenant_slug)
        user = await self._get_user_by_email(email, tenant.id)
        if user and not user.preferences.get("email_verified"):
            await self._send_verification_email(user)

    # ── Internal helpers ──────────────────────────────────────────────────────

    async def _complete_login(
        self,
        *,
        user: User,
        tenant: Tenant,
        request: Request,
        device_name: str | None = None,
    ) -> dict[str, Any]:
        roles, permissions = await self._get_roles_permissions(user)
        session_id = secrets.token_urlsafe(32)
        jti = secrets.token_urlsafe(32)

        access_token = create_access_token(
            sub=str(user.id),
            tenant_id=str(tenant.id),
            roles=roles,
            permissions=permissions,
            session_id=session_id,
            jti=jti,
            extra={"username": user.display_name or user.email.split("@")[0], "email": user.email},
        )
        refresh_token = create_refresh_token(
            sub=str(user.id),
            tenant_id=str(tenant.id),
            session_id=session_id,
            jti=jti,
        )

        device = await self._device_svc.upsert_device(
            user=user, request=request, device_name=device_name
        ) if settings.DEVICE_TRACKING_ENABLED else None

        expires_at = datetime.now(UTC) + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)
        session = UserSession(
            tenant_id=tenant.id,
            user_id=user.id,
            refresh_jti=jti,
            device_id=device.id if device else None,
            ip_address=request.client.host if (request and request.client) else None,
            user_agent=request.headers.get("user-agent") if request else None,
            expires_at=expires_at,
            last_active_at=datetime.now(UTC),
        )
        self.db.add(session)

        user.last_login_at = datetime.now(UTC)
        await self.db.flush()

        await store_session(
            session_id,
            {
                "user_id": str(user.id),
                "tenant_id": str(tenant.id),
                "session_db_id": str(session.id),
                "roles": roles,
            },
            ttl=settings.REDIS_SESSION_TTL_SECONDS,
        )

        log.info("login_success", user_id=str(user.id), tenant=tenant.slug)
        return {
            "access_token": access_token,
            "refresh_token": refresh_token,
            "token_type": "bearer",
            "expires_in": settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
            "session_id": session_id,
            "mfa_required": False,
        }

    async def _get_tenant(self, slug: str) -> Tenant:
        result = await self.db.execute(
            select(Tenant).where(
                Tenant.slug == slug,
                Tenant.deleted_at.is_(None),
            )
        )
        tenant = result.scalar_one_or_none()
        if not tenant:
            raise AuthError("Tenant not found.", "tenant_not_found")
        return tenant

    async def _get_user_by_email(self, email: str, tenant_id: UUID) -> User | None:
        result = await self.db.execute(
            select(User).where(
                User.tenant_id == tenant_id,
                User.email == email.lower(),
                User.deleted_at.is_(None),
            )
        )
        return result.scalar_one_or_none()

    async def _get_roles_permissions(self, user: User) -> tuple[list[str], list[str]]:
        from sg_db.models.identity import Permission, Role, RolePermission, UserRole
        result = await self.db.execute(
            select(Role).join(UserRole, Role.id == UserRole.role_id).where(
                UserRole.user_id == user.id,
                Role.deleted_at.is_(None),
            )
        )
        roles = result.scalars().all()
        role_names = [r.name for r in roles]

        perms: list[str] = []
        for role in roles:
            perm_result = await self.db.execute(
                select(Permission).join(
                    RolePermission, Permission.id == RolePermission.permission_id
                ).where(RolePermission.role_id == role.id)
            )
            perms.extend(
                f"{p.resource}:{p.action}" for p in perm_result.scalars().all()
            )

        return role_names, list(set(perms))

    async def _get_session_by_jti(self, jti: str) -> UserSession | None:
        result = await self.db.execute(
            select(UserSession).where(
                UserSession.refresh_jti == jti,
                UserSession.deleted_at.is_(None),
            )
        )
        return result.scalar_one_or_none()

    async def _verify_backup_code(self, user: User, code: str) -> bool:
        code_hash = hash_backup_code(code.upper())
        result = await self.db.execute(
            select(MfaBackupCode).where(
                MfaBackupCode.user_id == user.id,
                MfaBackupCode.code_hash == code_hash,
                MfaBackupCode.used_at.is_(None),
            )
        )
        bc = result.scalar_one_or_none()
        if bc:
            bc.used_at = datetime.now(UTC)
            return True
        return False

    async def _send_verification_email(self, user: User) -> None:
        token = generate_opaque_token(32)
        token_hash = hashlib.sha256(token.encode()).hexdigest()
        expires = datetime.now(UTC) + timedelta(hours=settings.EMAIL_VERIFICATION_EXPIRE_HOURS)

        self.db.add(EmailVerificationToken(
            tenant_id=user.tenant_id,
            user_id=user.id,
            email=user.email,
            token_hash=token_hash,
            expires_at=expires,
        ))

        await self._email_svc.send_verification(email=user.email, token=token)
