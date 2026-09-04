"""
Unit tests for Kite Connect authentication, token management, and session endpoints.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.auth import get_current_user
from app.brokers.interface import AuthenticationError
from app.brokers.kite.broker import KiteBroker
from app.core.config import get_settings
from app.main import create_app
from sg_security.jwt_auth import CurrentUser

settings = get_settings()


def _mock_admin_user():
    return CurrentUser(sub="test_admin", roles=["admin", "risk_officer"], tenant_id="default", raw_claims={})


def test_get_kite_login_url_endpoint():
    """Verify GET /v1/broker/kite/login-url returns valid Zerodha OAuth login URL."""
    with patch("app.main.init_broker", new=AsyncMock()), \
         patch("app.main.shutdown_broker", new=AsyncMock()), \
         patch("app.main.get_redis", new=AsyncMock()):

        app = create_app()
        app.dependency_overrides[get_current_user] = _mock_admin_user
        client = TestClient(app)

        response = client.get("/v1/broker/kite/login-url")
        assert response.status_code == 200
        data = response.json()
        assert "login_url" in data
        assert "kite.zerodha.com/connect/login" in data["login_url"]
        assert f"api_key={settings.KITE_API_KEY}" in data["login_url"]


def test_post_kite_session_endpoint_in_paper_mode():
    """Verify POST /v1/broker/kite/session rejects requests when broker is in paper mode."""
    mock_paper_broker = MagicMock()
    mock_paper_broker.broker_name = "paper"

    with patch("app.main.init_broker", new=AsyncMock()), \
         patch("app.main.shutdown_broker", new=AsyncMock()), \
         patch("app.main.get_redis", new=AsyncMock()), \
         patch("app.api.v1.endpoints.broker.get_broker", new=AsyncMock(return_value=mock_paper_broker)):

        app = create_app()
        app.dependency_overrides[get_current_user] = _mock_admin_user
        client = TestClient(app)

        response = client.post("/v1/broker/kite/session", json={"request_token": "dummy_request_token"})
        assert response.status_code == 400
        assert "paper" in response.json()["detail"].lower()


def test_post_kite_session_endpoint_in_live_mode():
    """Verify POST /v1/broker/kite/session generates token when broker is in live mode."""
    mock_kite_broker = MagicMock()
    mock_kite_broker.broker_name = "kite"
    mock_kite_broker.generate_session = AsyncMock(return_value="live_token_98765")

    with patch("app.main.init_broker", new=AsyncMock()), \
         patch("app.main.shutdown_broker", new=AsyncMock()), \
         patch("app.main.get_redis", new=AsyncMock()), \
         patch("app.api.v1.endpoints.broker.get_broker", new=AsyncMock(return_value=mock_kite_broker)):

        app = create_app()
        app.dependency_overrides[get_current_user] = _mock_admin_user
        client = TestClient(app)

        response = client.post("/v1/broker/kite/session", json={"request_token": "valid_request_token"})
        assert response.status_code == 200
        data = response.json()
        assert data["ok"] is True
        assert "activated" in data["message"]
        mock_kite_broker.generate_session.assert_awaited_once_with("valid_request_token")


@pytest.mark.asyncio
async def test_kite_broker_generate_session_flow():
    """Verify KiteBroker.generate_session exchanges token, saves to Redis, and publishes pubsub."""
    mock_redis = AsyncMock()

    with patch("app.brokers.factory.verify_live_trading_guard"), \
         patch("app.core.redis.get_redis", new=AsyncMock(return_value=mock_redis)):

        broker = KiteBroker()
        broker._kite.generate_session = MagicMock(return_value={"access_token": "mock_live_access_token_12345"})
        broker.connect = AsyncMock()

        token = await broker.generate_session("test_req_token_abc")

        assert token == "mock_live_access_token_12345"
        mock_redis.set.assert_awaited_once_with("sg:kite:access_token", "mock_live_access_token_12345", ex=93600)
        mock_redis.publish.assert_awaited_once_with("sg:kite:token_refreshed", "refreshed")
        broker.connect.assert_awaited_once()


@pytest.mark.asyncio
async def test_token_exception_triggers_kill_switch():
    """Verify mid-day TokenException triggers the kill switch and raises AuthenticationError."""
    from kiteconnect.exceptions import TokenException

    with patch("app.brokers.factory.verify_live_trading_guard"):
        broker = KiteBroker()
        broker._trigger_kill_switch = AsyncMock()
        broker._run = AsyncMock(side_effect=TokenException("Token is invalid or expired"))

        with pytest.raises(AuthenticationError):
            await broker._execute_with_retry(broker._kite.profile)

        broker._trigger_kill_switch.assert_awaited_once()
        call_arg = broker._trigger_kill_switch.call_args[0][0]
        assert "KITE_TOKEN_EXCEPTION" in call_arg


@pytest.mark.asyncio
async def test_disconnected_broker_cannot_place_order():
    """Verify that a disconnected KiteBroker raises AuthenticationError immediately on place_order."""
    from app.core.types import OrderRequest, Exchange, OrderSide, OrderType, ProductType

    with patch("app.brokers.factory.verify_live_trading_guard"):
        broker = KiteBroker()
        assert broker.is_connected is False

        req = OrderRequest(
            symbol="RELIANCE", exchange=Exchange.NSE, side=OrderSide.BUY,
            order_type=OrderType.MARKET, product=ProductType.MIS, quantity=1,
        )

        with pytest.raises(AuthenticationError) as exc_info:
            await broker.place_order(req)

        assert "disconnected or unauthenticated" in str(exc_info.value).lower()

