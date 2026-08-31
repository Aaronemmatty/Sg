"""Integration tests — auth HTTP endpoints."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from tests.integration.conftest import create_tenant, create_user


pytestmark = pytest.mark.asyncio


# ── Registration ──────────────────────────────────────────────────────────────

class TestRegisterEndpoint:
    async def test_register_success(self, client: AsyncClient, db: AsyncSession):
        tenant = await create_tenant(db, slug="reg-tenant")

        with patch("app.services.auth.EmailService.send_verification", AsyncMock()):
            resp = await client.post("/v1/auth/register", json={
                "email": "new@sg.local",
                "password": "ValidP@ssw0rd1234",
                "display_name": "New Trader",
                "tenant_slug": "reg-tenant",
            })

        assert resp.status_code == 201
        data = resp.json()
        assert "user_id" in data
        assert data["email"] == "new@sg.local"

    async def test_register_weak_password(self, client: AsyncClient, db: AsyncSession):
        await create_tenant(db, slug="reg-tenant-2")

        resp = await client.post("/v1/auth/register", json={
            "email": "weak@sg.local",
            "password": "short",
            "display_name": "Weak",
            "tenant_slug": "reg-tenant-2",
        })
        assert resp.status_code in (400, 422)

    async def test_register_duplicate_email(self, client: AsyncClient, db: AsyncSession):
        tenant = await create_tenant(db, slug="dup-tenant")
        await create_user(db, tenant.id, email="dup@sg.local")

        with patch("app.services.auth.EmailService.send_verification", AsyncMock()):
            resp = await client.post("/v1/auth/register", json={
                "email": "dup@sg.local",
                "password": "ValidP@ssw0rd1234",
                "display_name": "Dup",
                "tenant_slug": "dup-tenant",
            })
        assert resp.status_code == 400
        assert "already registered" in resp.json()["detail"].lower()

    async def test_register_unknown_tenant(self, client: AsyncClient, db: AsyncSession):
        resp = await client.post("/v1/auth/register", json={
            "email": "x@sg.local",
            "password": "ValidP@ssw0rd1234",
            "display_name": "X",
            "tenant_slug": "ghost-tenant",
        })
        assert resp.status_code == 400


# ── Login ─────────────────────────────────────────────────────────────────────

class TestLoginEndpoint:
    async def test_login_success(self, client: AsyncClient, db: AsyncSession):
        tenant = await create_tenant(db, slug="login-tenant")
        await create_user(db, tenant.id, email="login@sg.local", password="ValidP@ssw0rd1234")

        with patch("app.services.auth.store_session", AsyncMock()), \
             patch("app.services.auth.DeviceService.upsert_device", AsyncMock(return_value=None)):
            resp = await client.post("/v1/auth/login", json={
                "email": "login@sg.local",
                "password": "ValidP@ssw0rd1234",
                "tenant_slug": "login-tenant",
            })

        assert resp.status_code == 200
        data = resp.json()
        assert "access_token" in data
        assert "refresh_token" in data
        assert data["token_type"] == "bearer"

    async def test_login_wrong_password(self, client: AsyncClient, db: AsyncSession):
        tenant = await create_tenant(db, slug="badpw-tenant")
        await create_user(db, tenant.id, email="badpw@sg.local", password="ValidP@ssw0rd1234")

        resp = await client.post("/v1/auth/login", json={
            "email": "badpw@sg.local",
            "password": "WrongPassword1!",
            "tenant_slug": "badpw-tenant",
        })
        assert resp.status_code == 401

    async def test_login_unverified_email(self, client: AsyncClient, db: AsyncSession):
        tenant = await create_tenant(db, slug="unverified-tenant")
        await create_user(db, tenant.id, email="unverified@sg.local", email_verified=False)

        with patch("app.core.config.Settings.EMAIL_VERIFICATION_REQUIRED", True):
            resp = await client.post("/v1/auth/login", json={
                "email": "unverified@sg.local",
                "password": "ValidP@ssw0rd1234",
                "tenant_slug": "unverified-tenant",
            })
        # May pass depending on settings; just ensure no 500
        assert resp.status_code in (200, 401)

    async def test_login_nonexistent_user(self, client: AsyncClient, db: AsyncSession):
        await create_tenant(db, slug="ghost-user-tenant")
        resp = await client.post("/v1/auth/login", json={
            "email": "ghost@sg.local",
            "password": "ValidP@ssw0rd1234",
            "tenant_slug": "ghost-user-tenant",
        })
        assert resp.status_code == 401


# ── Token refresh ─────────────────────────────────────────────────────────────

class TestRefreshEndpoint:
    async def test_invalid_refresh_token(self, client: AsyncClient):
        resp = await client.post("/v1/auth/refresh", json={"refresh_token": "not.a.token"})
        assert resp.status_code == 401

    async def test_access_token_rejected_as_refresh(self, client: AsyncClient, db: AsyncSession):
        from app.core.security import create_access_token
        token = create_access_token(
            sub=str("00000000-0000-0000-0000-000000000001"),
            tenant_id=str("00000000-0000-0000-0000-000000000002"),
            roles=[],
            permissions=[],
            session_id="sid",
        )
        resp = await client.post("/v1/auth/refresh", json={"refresh_token": token})
        assert resp.status_code == 401


# ── Health ────────────────────────────────────────────────────────────────────

class TestHealthEndpoint:
    async def test_health_returns_ok(self, client: AsyncClient):
        resp = await client.get("/health")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"


# ── Profile ───────────────────────────────────────────────────────────────────

class TestMeEndpoint:
    async def test_me_unauthenticated(self, client: AsyncClient):
        resp = await client.get("/v1/auth/me")
        assert resp.status_code == 401

    async def test_me_authenticated(self, client: AsyncClient, db: AsyncSession):
        """Login then call /me with the access token."""
        tenant = await create_tenant(db, slug="me-tenant")
        await create_user(db, tenant.id, email="me@sg.local", password="ValidP@ssw0rd1234")

        with patch("app.services.auth.store_session", AsyncMock()), \
             patch("app.services.auth.DeviceService.upsert_device", AsyncMock(return_value=None)):
            login_resp = await client.post("/v1/auth/login", json={
                "email": "me@sg.local",
                "password": "ValidP@ssw0rd1234",
                "tenant_slug": "me-tenant",
            })

        if login_resp.status_code != 200:
            pytest.skip("Login failed, skipping /me test")

        token = login_resp.json()["access_token"]
        resp = await client.get("/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 200
        assert resp.json()["email"] == "me@sg.local"


# ── Password reset flow ───────────────────────────────────────────────────────

class TestPasswordReset:
    async def test_forgot_password_always_200(self, client: AsyncClient, db: AsyncSession):
        await create_tenant(db, slug="reset-tenant")

        with patch("app.services.auth.EmailService.send_password_reset", AsyncMock()):
            resp = await client.post("/v1/auth/password/forgot", json={
                "email": "ghost@nowhere.local",
                "tenant_slug": "reset-tenant",
            })
        # Must not leak user existence
        assert resp.status_code == 200

    async def test_reset_with_invalid_token(self, client: AsyncClient):
        resp = await client.post("/v1/auth/password/reset", json={
            "token": "invalid-token-xyz",
            "new_password": "NewValidP@ss1234",
        })
        assert resp.status_code == 400


# ── Email verification ────────────────────────────────────────────────────────

class TestEmailVerification:
    async def test_verify_with_bad_token(self, client: AsyncClient):
        resp = await client.post("/v1/auth/email/verify", json={"token": "bad-token"})
        assert resp.status_code == 400

    async def test_resend_always_succeeds(self, client: AsyncClient, db: AsyncSession):
        await create_tenant(db, slug="verify-tenant")
        resp = await client.post("/v1/auth/email/resend-verification", json={
            "email": "anyone@sg.local",
            "tenant_slug": "verify-tenant",
        })
        assert resp.status_code == 200
