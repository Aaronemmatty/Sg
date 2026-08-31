"""Unit tests — role-based authorization (AUTHZ-01 fix)."""
from __future__ import annotations

import pytest
from unittest.mock import MagicMock, patch
from fastapi import HTTPException, status

from app.auth import CurrentUser, get_current_user, require_role, require_any_role


class TestRequireRoleNoAdminBypass:
    """Test the critical AUTHZ-01 fix: admin role no longer bypasses all role checks."""

    @pytest.mark.asyncio
    async def test_admin_cannot_call_risk_officer_endpoints(self):
        """Admin token CANNOT call risk_officer-only endpoints → 403."""
        admin_user = CurrentUser(sub="admin_user", roles=["admin"])
        
        dependency = require_role("risk_officer")
        
        # Mock get_current_user to return admin user
        with patch("app.auth.get_current_user", return_value=admin_user):
            with pytest.raises(HTTPException) as exc_info:
                await dependency()
            
            assert exc_info.value.status_code == status.HTTP_403_FORBIDDEN
            assert "Requires role 'risk_officer'" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_risk_officer_can_call_risk_officer_endpoints(self):
        """risk_officer token CAN call risk_officer endpoints → 200."""
        risk_officer_user = CurrentUser(sub="risk_user", roles=["risk_officer"])
        
        dependency = require_role("risk_officer")
        
        with patch("app.auth.get_current_user", return_value=risk_officer_user):
            result = await dependency()
            assert result.sub == "risk_user"
            assert result.roles == ["risk_officer"]

    @pytest.mark.asyncio
    async def test_admin_can_call_admin_only_endpoints(self):
        """Admin token CAN call admin-only endpoints → 200."""
        admin_user = CurrentUser(sub="admin_user", roles=["admin"])
        
        dependency = require_role("admin")
        
        with patch("app.auth.get_current_user", return_value=admin_user):
            result = await dependency()
            assert result.sub == "admin_user"
            assert result.roles == ["admin"]

    @pytest.mark.asyncio
    async def test_no_token_returns_401(self):
        """No token → 401 on all endpoints."""
        with patch("app.auth.get_current_user", side_effect=HTTPException(status_code=401, detail="Missing bearer token")):
            with pytest.raises(HTTPException) as exc_info:
                await get_current_user(None, MagicMock())
            
            assert exc_info.value.status_code == status.HTTP_401_UNAUTHORIZED

    @pytest.mark.asyncio
    async def test_trader_cannot_call_risk_officer_endpoints(self):
        """Trader token CANNOT call risk_officer endpoints → 403."""
        trader_user = CurrentUser(sub="trader_user", roles=["trader"])
        
        dependency = require_role("risk_officer")
        
        with patch("app.auth.get_current_user", return_value=trader_user):
            with pytest.raises(HTTPException) as exc_info:
                await dependency()
            
            assert exc_info.value.status_code == status.HTTP_403_FORBIDDEN

    @pytest.mark.asyncio
    async def test_user_with_multiple_roles_passes_if_has_required(self):
        """User with multiple roles passes if they have the required role."""
        multi_role_user = CurrentUser(sub="multi_user", roles=["trader", "risk_officer", "admin"])
        
        dependency = require_role("risk_officer")
        
        with patch("app.auth.get_current_user", return_value=multi_role_user):
            result = await dependency()
            assert result.sub == "multi_user"


class TestRequireAnyRole:
    """Test the new require_any_role() helper for explicit multi-role gates."""

    @pytest.mark.asyncio
    async def test_require_any_role_passes_with_any_matching_role(self):
        """User passes if they have ANY of the required roles."""
        user = CurrentUser(sub="user", roles=["trader"])
        
        dependency = require_any_role(["risk_officer", "trader", "admin"])
        
        with patch("app.auth.get_current_user", return_value=user):
            result = await dependency()
            assert result.sub == "user"

    @pytest.mark.asyncio
    async def test_require_any_role_fails_without_any_matching_role(self):
        """User fails if they have NONE of the required roles."""
        user = CurrentUser(sub="user", roles=["analyst"])
        
        dependency = require_any_role(["risk_officer", "trader"])
        
        with patch("app.auth.get_current_user", return_value=user):
            with pytest.raises(HTTPException) as exc_info:
                await dependency()
            
            assert exc_info.value.status_code == status.HTTP_403_FORBIDDEN
            assert "Requires one of:" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_admin_bypass_removed_in_require_any_role(self):
        """Admin role does NOT bypass require_any_role (no implicit bypass)."""
        admin_user = CurrentUser(sub="admin", roles=["admin"])
        
        dependency = require_any_role(["risk_officer", "trader"])
        
        with patch("app.auth.get_current_user", return_value=admin_user):
            with pytest.raises(HTTPException) as exc_info:
                await dependency()
            
            assert exc_info.value.status_code == status.HTTP_403_FORBIDDEN


class TestCurrentUser:
    """Test CurrentUser helper methods."""

    def test_has_role_true(self):
        user = CurrentUser(sub="user", roles=["trader", "admin"])
        assert user.has_role("trader") is True
        assert user.has_role("admin") is True

    def test_has_role_false(self):
        user = CurrentUser(sub="user", roles=["trader", "admin"])
        assert user.has_role("risk_officer") is False
        assert user.has_role("") is False
