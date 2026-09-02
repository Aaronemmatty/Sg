"""Unit tests for pre-trade market-hours gating in broker_service."""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
from zoneinfo import ZoneInfo

from app.brokers.paper.broker import PaperBroker
from app.core.types import (
    AccountInfo,
    Exchange,
    OrderRequest,
    OrderSide,
    OrderType,
    ProductType,
)
from app.risk.engine import RiskEngine
from app.services.order import OrderService
from sg_security.calendar import IST


@pytest.fixture
def mock_broker():
    broker = MagicMock(spec=PaperBroker)
    broker.get_account_info = AsyncMock(
        return_value=AccountInfo(
            broker="paper",
            account_id="test_acc",
            available_cash=10000.0,
            used_margin=0.0,
            total_margin=10000.0,
            net_value=10000.0,
            day_pnl=0.0,
            positions_value=0.0,
        )
    )
    broker.get_positions = AsyncMock(return_value=[])
    broker.place_order = AsyncMock()
    return broker


@pytest.fixture
def valid_order_request():
    return OrderRequest(
        symbol="NSE:TATAMOTORS",
        exchange=Exchange.NSE,
        side=OrderSide.BUY,
        order_type=OrderType.LIMIT,
        product=ProductType.MIS,
        quantity=2,
        price=450.0,
    )


@pytest.mark.asyncio
async def test_pre_trade_rejects_at_0914_ist(mock_broker, valid_order_request):
    """09:14:59 IST (pre-open/closed for continuous trading) -> rejected."""
    engine = RiskEngine()
    dt_0914 = datetime(2026, 3, 4, 9, 14, 59, tzinfo=IST)

    result = await engine.pre_trade_check(valid_order_request, mock_broker, now_dt=dt_0914)
    assert result.passed is False
    assert any(v.rule == "MARKET_HOURS" for v in result.violations)


@pytest.mark.asyncio
async def test_pre_trade_allows_at_0915_ist(mock_broker, valid_order_request):
    """09:15:00 IST (exact market open) -> allowed."""
    engine = RiskEngine()
    dt_0915 = datetime(2026, 3, 4, 9, 15, 0, tzinfo=IST)

    result = await engine.pre_trade_check(valid_order_request, mock_broker, now_dt=dt_0915)
    assert result.passed is True
    assert len(result.violations) == 0


@pytest.mark.asyncio
async def test_pre_trade_allows_at_0920_ist(mock_broker, valid_order_request):
    """09:20:00 IST (regular continuous session) -> allowed."""
    engine = RiskEngine()
    dt_0920 = datetime(2026, 3, 4, 9, 20, 0, tzinfo=IST)

    result = await engine.pre_trade_check(valid_order_request, mock_broker, now_dt=dt_0920)
    assert result.passed is True
    assert len(result.violations) == 0


@pytest.mark.asyncio
async def test_pre_trade_allows_at_1530_ist(mock_broker, valid_order_request):
    """15:30:00 IST (closing boundary) -> allowed."""
    engine = RiskEngine()
    dt_1530 = datetime(2026, 3, 4, 15, 30, 0, tzinfo=IST)

    result = await engine.pre_trade_check(valid_order_request, mock_broker, now_dt=dt_1530)
    assert result.passed is True
    assert len(result.violations) == 0


@pytest.mark.asyncio
async def test_pre_trade_rejects_at_1531_ist(mock_broker, valid_order_request):
    """15:31:00 IST (post-market close) -> rejected."""
    engine = RiskEngine()
    dt_1531 = datetime(2026, 3, 4, 15, 31, 0, tzinfo=IST)

    result = await engine.pre_trade_check(valid_order_request, mock_broker, now_dt=dt_1531)
    assert result.passed is False
    assert any(v.rule == "MARKET_HOURS" for v in result.violations)


@pytest.mark.asyncio
async def test_pre_trade_rejects_on_saturday_and_sunday(mock_broker, valid_order_request):
    """Weekends (Saturday/Sunday) -> rejected."""
    engine = RiskEngine()
    dt_sat = datetime(2026, 3, 7, 11, 0, 0, tzinfo=IST)
    dt_sun = datetime(2026, 3, 8, 11, 0, 0, tzinfo=IST)

    res_sat = await engine.pre_trade_check(valid_order_request, mock_broker, now_dt=dt_sat)
    res_sun = await engine.pre_trade_check(valid_order_request, mock_broker, now_dt=dt_sun)

    assert res_sat.passed is False
    assert any(v.rule == "MARKET_HOURS" for v in res_sat.violations)

    assert res_sun.passed is False
    assert any(v.rule == "MARKET_HOURS" for v in res_sun.violations)


@pytest.mark.asyncio
async def test_pre_trade_rejects_on_nse_holiday(mock_broker, valid_order_request):
    """NSE Holiday (e.g. 2026-01-26 Republic Day) -> rejected."""
    engine = RiskEngine()
    dt_holiday = datetime(2026, 1, 26, 11, 0, 0, tzinfo=IST)

    result = await engine.pre_trade_check(valid_order_request, mock_broker, now_dt=dt_holiday)
    assert result.passed is False
    assert any(v.rule == "MARKET_HOURS" for v in result.violations)


@pytest.mark.asyncio
async def test_utc_timezone_awareness_in_risk_check(mock_broker, valid_order_request):
    """03:45 UTC = 09:15 IST (allowed); 03:44 UTC = 09:14 IST (rejected)."""
    engine = RiskEngine()
    utc_open = datetime(2026, 3, 4, 3, 45, 0, tzinfo=timezone.utc)
    utc_closed = datetime(2026, 3, 4, 3, 44, 0, tzinfo=timezone.utc)

    res_open = await engine.pre_trade_check(valid_order_request, mock_broker, now_dt=utc_open)
    res_closed = await engine.pre_trade_check(valid_order_request, mock_broker, now_dt=utc_closed)

    assert res_open.passed is True
    assert res_closed.passed is False
    assert any(v.rule == "MARKET_HOURS" for v in res_closed.violations)
