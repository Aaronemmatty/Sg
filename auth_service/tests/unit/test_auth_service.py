"""Unit tests — AuthService (mocked DB and Redis)."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.services.auth import AuthError, AuthService


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_user(**kwargs):
    u = MagicMock()
    u.id = kwargs.get("id", uuid4())
    u.email = kwargs.get("email", "trader@sg.local")
    u.password_hash = kwargs.get("password_hash", "$2b$12$fakehash")
    u.is_active = kwargs.get("is_active", True)
    u.mfa_enabled = kwargs.get("mfa_enabled", False)
    u.mfa_secret = kwargs.get("mfa_secret", None)
    u.tenant_id = kwargs.get("tenant_id", uuid4())
    u.preferences = kwargs.get("preferences", {"email_verified": True})
    u.last_login_at = None
    return u


def _make_tenant(**kwargs):
    t = MagicMock()
    t.id = kwargs.get("id", uuid4())
    t.slug = kwargs.get("slug", "default")
    return t


@pytest.fixture
def mock_db():
    db = AsyncMock()
    db.flush = AsyncMock()
    db.add = MagicMock()
    return db


@pytest.fixture
def mock_request():
    req = MagicMock()
    req.client.host = "127.0.0.1"
    req.headers = {"user-agent": "pytest/1.0"}
    return req


@pytest.fixture
def auth_svc(mock_db, mock_request):
    svc = AuthService(db=mock_db, request=mock_request)
    svc._email_svc = AsyncMock()
    svc._device_svc = AsyncMock()
    svc._device_svc.upsert_device = AsyncMock(return_value=MagicMock(id=uuid4()))
    return svc


# ── Registration ──────────────────────────────────────────────────────────────

class TestRegister:
    @pytest.mark.asyncio
    async def test_weak_password_raises(self, auth_svc, mock_db):
        tenant = _make_tenant()
        auth_svc._get_tenant = AsyncMock(return_value=tenant)

        with pytest.raises(AuthError) as exc:
            await auth_svc.register(
                email="x@x.com",
                password="weak",
                display_name="Trader",
                tenant_slug="default",
            )
        assert exc.value.code == "weak_password"

    @pytest.mark.asyncio
    async def test_duplicate_email_raises(self, auth_svc, mock_db):
        tenant = _make_tenant()
        auth_svc._get_tenant = AsyncMock(return_value=tenant)

        existing_user = _make_user()
        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = existing_user
        mock_db.execute = AsyncMock(return_value=result_mock)

        with pytest.raises(AuthError) as exc:
            await auth_svc.register(
                email="dup@sg.local",
                password="ValidP@ssw0rd1234",
                display_name="Dup",
                tenant_slug="default",
            )
        assert exc.value.code == "email_exists"

    @pytest.mark.asyncio
    async def test_successful_registration(self, auth_svc, mock_db):
        tenant = _make_tenant()
        auth_svc._get_tenant = AsyncMock(return_value=tenant)
        auth_svc._send_verification_email = AsyncMock()

        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = None
        mock_db.execute = AsyncMock(return_value=result_mock)

        with patch("app.services.auth.get_settings") as mock_settings:
            mock_settings.return_value.EMAIL_VERIFICATION_REQUIRED = False
            user = await auth_svc.register(
                email="new@sg.local",
                password="ValidP@ssw0rd1234",
                display_name="New Trader",
                tenant_slug="default",
            )
        assert mock_db.add.called


# ── Login ─────────────────────────────────────────────────────────────────────

class TestLogin:
    @pytest.mark.asyncio
    async def test_locked_account_raises(self, auth_svc, mock_request):
        auth_svc._get_tenant = AsyncMock(return_value=_make_tenant())
        with patch("app.services.auth.is_locked_out", AsyncMock(return_value=True)):
            with pytest.raises(AuthError) as exc:
                await auth_svc.login(
                    email="x@x.com",
                    password="pw",
                    tenant_slug="default",
                    request=mock_request,
                )
            assert exc.value.code == "account_locked"

    @pytest.mark.asyncio
    async def test_invalid_credentials_raises(self, auth_svc, mock_request):
        tenant = _make_tenant()
        user = _make_user()
        auth_svc._get_tenant = AsyncMock(return_value=tenant)
        auth_svc._get_user_by_email = AsyncMock(return_value=user)

        with patch("app.services.auth.is_locked_out", AsyncMock(return_value=False)), \
             patch("app.services.auth.verify_password", return_value=False), \
             patch("app.services.auth.increment_login_attempts", AsyncMock(return_value=1)):
            with pytest.raises(AuthError) as exc:
                await auth_svc.login(
                    email=user.email,
                    password="wrong",
                    tenant_slug="default",
                    request=mock_request,
                )
            assert exc.value.code == "invalid_credentials"

    @pytest.mark.asyncio
    async def test_mfa_required_returns_challenge(self, auth_svc, mock_request):
        tenant = _make_tenant()
        user = _make_user(mfa_enabled=True, mfa_secret="JBSWY3DPEHPK3PXP")
        auth_svc._get_tenant = AsyncMock(return_value=tenant)
        auth_svc._get_user_by_email = AsyncMock(return_value=user)

        with patch("app.services.auth.is_locked_out", AsyncMock(return_value=False)), \
             patch("app.services.auth.verify_password", return_value=True), \
             patch("app.services.auth.clear_login_attempts", AsyncMock()), \
             patch("app.services.auth.store_mfa_challenge", AsyncMock()):
            result = await auth_svc.login(
                email=user.email,
                password="ValidP@ss1!",
                tenant_slug="default",
                request=mock_request,
            )
        assert result["mfa_required"] is True
        assert "challenge_id" in result

    @pytest.mark.asyncio
    async def test_inactive_user_raises(self, auth_svc, mock_request):
        tenant = _make_tenant()
        user = _make_user(is_active=False)
        auth_svc._get_tenant = AsyncMock(return_value=tenant)
        auth_svc._get_user_by_email = AsyncMock(return_value=user)

        with patch("app.services.auth.is_locked_out", AsyncMock(return_value=False)), \
             patch("app.services.auth.verify_password", return_value=True), \
             patch("app.services.auth.clear_login_attempts", AsyncMock()):
            with pytest.raises(AuthError) as exc:
                await auth_svc.login(
                    email=user.email,
                    password="any",
                    tenant_slug="default",
                    request=mock_request,
                )
            assert exc.value.code == "account_disabled"


# ── Password ──────────────────────────────────────────────────────────────────

class TestPasswordChange:
    @pytest.mark.asyncio
    async def test_wrong_old_password_raises(self, auth_svc):
        user = _make_user()
        with patch("app.services.auth.verify_password", return_value=False):
            with pytest.raises(AuthError) as exc:
                await auth_svc.change_password(
                    user=user,
                    old_password="wrong",
                    new_password="NewValidP@ss1234",
                )
            assert exc.value.code == "invalid_credentials"

    @pytest.mark.asyncio
    async def test_successful_password_change(self, auth_svc):
        user = _make_user()
        with patch("app.services.auth.verify_password", return_value=True), \
             patch("app.services.auth.delete_all_user_sessions", AsyncMock()):
            await auth_svc.change_password(
                user=user,
                old_password="OldP@ss1234",
                new_password="NewP@ssword1234!",
            )
        assert user.password_hash != ""
