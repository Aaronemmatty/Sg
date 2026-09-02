"""Unit tests — JWT authentication behavior (AUTH-01 fix)."""
from __future__ import annotations

import pytest
from unittest.mock import patch, MagicMock
from fastapi import HTTPException, status

from app.core.security import verify_token, _is_production, require_role


class TestSecurityAuth:
    """Test the critical AUTH-01 fix: fail-closed in production when key missing."""

    @pytest.mark.asyncio
    async def test_valid_token_with_public_key_returns_200(self):
        """With valid JWT_PUBLIC_KEY set + valid token → 200 (success)."""
        mock_creds = MagicMock()
        mock_creds.credentials = "valid_token"

        with patch("app.core.security._load_public_key", return_value="mock_public_key"), \
             patch("app.core.security.jwt.decode", return_value={"sub": "user123", "roles": ["analyst"]}) as mock_decode:
            result = await verify_token(mock_creds)
            assert result["sub"] == "user123"
            assert result["roles"] == ["analyst"]
            mock_decode.assert_called_once()

    @pytest.mark.asyncio
    async def test_no_token_with_public_key_returns_401(self):
        """With valid JWT_PUBLIC_KEY set + no token → 401."""
        with patch("app.core.security._load_public_key", return_value="mock_public_key"):
            with pytest.raises(HTTPException) as exc_info:
                await verify_token(None)
            assert exc_info.value.status_code == status.HTTP_401_UNAUTHORIZED
            assert "Missing bearer token" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_missing_key_in_development_returns_stub_user(self):
        """With JWT_PUBLIC_KEY = "" and env = "development" → stub user (200)."""
        mock_settings = MagicMock()
        mock_settings.AUTH_REQUIRED = True
        mock_settings.env = "development"
        mock_settings.JWT_ISSUER = None

        with patch("app.core.security.get_settings", return_value=mock_settings), \
             patch("app.core.security._load_public_key", return_value=None):
            result = await verify_token(None)
            assert result["sub"] == "dev"
            assert "analyst" in result["roles"]
            assert "risk_officer" in result["roles"]

    @pytest.mark.asyncio
    async def test_missing_key_in_production_returns_503(self):
        """With JWT_PUBLIC_KEY = "" and env = "production" → 503 (critical fix)."""
        mock_settings = MagicMock()
        mock_settings.AUTH_REQUIRED = True
        mock_settings.env = "production"
        mock_settings.JWT_ISSUER = None

        with patch("app.core.security.get_settings", return_value=mock_settings), \
             patch("app.core.security._load_public_key", return_value=None):
            with pytest.raises(HTTPException) as exc_info:
                await verify_token(None)
            assert exc_info.value.status_code == status.HTTP_503_SERVICE_UNAVAILABLE
            assert "Auth verification unavailable" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_auth_required_false_in_production_returns_503(self):
        """AUTH_REQUIRED=False in production → 503 (fail-closed)."""
        mock_settings = MagicMock()
        mock_settings.AUTH_REQUIRED = False
        mock_settings.env = "production"
        mock_settings.DEFAULT_TENANT_ID = "default"

        with patch("app.core.security.get_settings", return_value=mock_settings):
            with pytest.raises(HTTPException) as exc_info:
                await verify_token(None)
            assert exc_info.value.status_code == status.HTTP_503_SERVICE_UNAVAILABLE
            assert "Auth verification misconfigured" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_auth_required_false_in_development_returns_anonymous(self):
        """AUTH_REQUIRED=False in development → anonymous user."""
        mock_settings = MagicMock()
        mock_settings.AUTH_REQUIRED = False
        mock_settings.env = "development"
        mock_settings.DEFAULT_TENANT_ID = "default"

        with patch("app.core.security.get_settings", return_value=mock_settings):
            result = await verify_token(None)
            assert result["sub"] == "anonymous"
            assert result["tenant_id"] == "default"
            assert result["roles"] == []

    @pytest.mark.asyncio
    async def test_invalid_token_returns_401(self):
        """Invalid token signature → 401."""
        mock_creds = MagicMock()
        mock_creds.credentials = "invalid_token"
        mock_settings = MagicMock()
        mock_settings.AUTH_REQUIRED = True
        mock_settings.env = "production"
        mock_settings.JWT_ISSUER = None

        with patch("app.core.security.get_settings", return_value=mock_settings), \
             patch("app.core.security._load_public_key", return_value="mock_key"), \
             patch("app.core.security.jwt.decode", side_effect=Exception("Invalid signature")):
            with pytest.raises(HTTPException) as exc_info:
                await verify_token(mock_creds)
            assert exc_info.value.status_code == status.HTTP_401_UNAUTHORIZED
            assert "Invalid token" in exc_info.value.detail

    def test_is_production_true(self):
        """_is_production returns True when env is 'production' or 'prod' (case-insensitive)."""
        mock_settings = MagicMock()
        mock_settings.env = "production"
        assert _is_production(mock_settings) is True

        mock_settings.env = None
        mock_settings.ENV = "prod"
        assert _is_production(mock_settings) is True

        mock_settings.ENV = "PROD"
        assert _is_production(mock_settings) is True

    def test_is_production_false(self):
        """_is_production returns False for non-production envs."""
        mock_settings = MagicMock()
        mock_settings.env = "development"
        mock_settings.ENV = "dev"
        assert _is_production(mock_settings) is False

        mock_settings.env = "staging"
        mock_settings.ENV = "staging"
        assert _is_production(mock_settings) is False

        mock_settings.env = None
        mock_settings.ENV = None
        assert _is_production(mock_settings) is False


class TestRequireRole:
    """Test the new require_role() dependency."""

    @pytest.mark.asyncio
    async def test_require_role_passes_with_correct_role(self):
        """User with required role passes."""
        dependency = require_role("analyst")
        result = await dependency(claims={"sub": "user", "roles": ["analyst"]})
        assert result["sub"] == "user"

    @pytest.mark.asyncio
    async def test_require_role_fails_without_role(self):
        """User without required role gets 403."""
        dependency = require_role("analyst")
        with pytest.raises(HTTPException) as exc_info:
            await dependency(claims={"sub": "user", "roles": ["trader"]})
        assert exc_info.value.status_code == status.HTTP_403_FORBIDDEN
        assert "Requires role 'analyst'" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_require_role_validates_roles_claim(self):
        """Non-list roles claim is sanitized to empty list."""
        mock_creds = MagicMock()
        mock_creds.credentials = "valid_token"

        with patch("app.core.security._load_public_key", return_value="mock_key"), \
             patch("app.core.security.jwt.decode", return_value={"sub": "user", "roles": "not_a_list"}):
            result = await verify_token(mock_creds)
            assert result["roles"] == []
