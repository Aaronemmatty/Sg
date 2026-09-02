"""Unit tests for the hard paper-vs-live safety switch and broker factory guard."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.brokers.factory import create_broker, verify_live_trading_guard
from app.brokers.interface import LiveTradingGuardError
from app.brokers.paper.broker import PaperBroker
from app.core.config import Settings


@pytest.mark.asyncio
async def test_paper_mode_returns_paper_broker():
    """Default paper mode initializes PaperBroker safely without live credentials."""
    broker = await create_broker(mode="paper")
    assert isinstance(broker, PaperBroker)
    assert broker.broker_name == "paper"
    assert broker.is_connected is True


@pytest.mark.asyncio
async def test_live_mode_with_missing_confirmation_refused():
    """Live mode without ENABLE_REAL_MONEY_TRADING must fail closed."""
    with patch("app.brokers.factory.get_settings") as mock_settings:
        mock_settings.return_value = Settings(
            BROKER_MODE="live",
            ENABLE_REAL_MONEY_TRADING="",
        )
        with pytest.raises(LiveTradingGuardError) as exc_info:
            await create_broker(mode="live")

        assert "LIVE REAL-MONEY TRADING REFUSED" in str(exc_info.value)
        assert "CONFIRMED_REAL_CAPITAL_RISK" in str(exc_info.value)


@pytest.mark.asyncio
async def test_live_mode_with_wrong_confirmation_refused():
    """Live mode with incorrect confirmation string must fail closed."""
    with patch("app.brokers.factory.get_settings") as mock_settings:
        mock_settings.return_value = Settings(
            BROKER_MODE="live",
            ENABLE_REAL_MONEY_TRADING="yes_please_trade_live",
        )
        with pytest.raises(LiveTradingGuardError) as exc_info:
            await create_broker(mode="live")

        assert "LIVE REAL-MONEY TRADING REFUSED" in str(exc_info.value)


@pytest.mark.asyncio
async def test_live_mode_with_correct_confirmation_allowed():
    """Live mode with exact CONFIRMED_REAL_CAPITAL_RISK confirmation initializes KiteBroker."""
    with patch("app.brokers.factory.get_settings") as mock_settings, \
         patch("app.brokers.kite.broker.settings") as mock_kite_settings, \
         patch("app.brokers.kite.broker.KiteConnect") as mock_kite_connect, \
         patch("app.brokers.kite.broker.KiteBroker.connect", new_callable=AsyncMock) as mock_connect:

        test_settings = Settings(
            BROKER_MODE="live",
            ENABLE_REAL_MONEY_TRADING="CONFIRMED_REAL_CAPITAL_RISK",
            KITE_API_KEY="test_api_key",
            KITE_ACCESS_TOKEN="test_access_token",
        )
        mock_settings.return_value = test_settings
        mock_kite_settings.ENABLE_REAL_MONEY_TRADING = "CONFIRMED_REAL_CAPITAL_RISK"
        mock_kite_settings.LIVE_CONFIRMATION_TOKEN = "CONFIRMED_REAL_CAPITAL_RISK"
        mock_kite_settings.KITE_API_KEY = "test_api_key"
        mock_kite_settings.KITE_ACCESS_TOKEN = "test_access_token"
        mock_kite_settings.KITE_EXECUTOR_WORKERS = 1

        broker = await create_broker(mode="live")
        assert broker.broker_name == "kite"
        mock_connect.assert_awaited_once()


@pytest.mark.asyncio
async def test_unknown_broker_mode_refused():
    """Unknown broker mode must raise ValueError."""
    with pytest.raises(ValueError) as exc_info:
        await create_broker(mode="simulated_real")

    assert "Unknown broker mode" in str(exc_info.value)


def test_direct_kite_broker_instantiation_blocked_without_guard():
    """Direct instantiation of KiteBroker without confirmation guard must raise LiveTradingGuardError."""
    with patch("app.core.config.get_settings") as mock_settings:
        mock_settings.return_value = Settings(
            BROKER_MODE="paper",
            ENABLE_REAL_MONEY_TRADING="",
        )
        from app.brokers.kite.broker import KiteBroker
        with pytest.raises(LiveTradingGuardError):
            KiteBroker()
