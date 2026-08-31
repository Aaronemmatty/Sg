from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from app.models.domain import (
    MarketSummaryRequest,
    PortfolioReviewRequest,
    RiskExplanationRequest,
    TradeReviewRequest,
)
from app.services.context_builder import (
    build_market_summary_context,
    build_portfolio_review_context,
    build_risk_explanation_context,
    build_trade_review_context,
)


@pytest.mark.asyncio
async def test_trade_review_context_collects_warning_on_unavailable_data():
    execution_client = AsyncMock()
    execution_client.get_recent_orders.return_value = {"available": False, "reason": "timeout"}
    execution_client.get_order.return_value = {"available": True, "data": {}}
    portfolio_client = AsyncMock()
    portfolio_client.get_recent_trades.return_value = {"available": True, "data": []}
    portfolio_client.get_position.return_value = {"available": True, "data": {}}

    req = TradeReviewRequest(symbol="RELIANCE", lookback_days=5)
    context, warnings = await build_trade_review_context(req, execution_client, portfolio_client)

    assert any("recent orders" in w for w in warnings)
    assert context["requested_symbol"] == "RELIANCE"
    assert context["lookback_days"] == 5


@pytest.mark.asyncio
async def test_trade_review_context_no_warnings_when_all_available():
    execution_client = AsyncMock()
    execution_client.get_recent_orders.return_value = {"available": True, "data": []}
    portfolio_client = AsyncMock()
    portfolio_client.get_recent_trades.return_value = {"available": True, "data": []}

    req = TradeReviewRequest()
    context, warnings = await build_trade_review_context(req, execution_client, portfolio_client)

    assert warnings == []
    assert context["order_detail"] is None  # no trade_id requested
    assert context["current_position"] is None  # no symbol requested


@pytest.mark.asyncio
async def test_portfolio_review_context_includes_positions_when_requested():
    portfolio_client = AsyncMock()
    portfolio_client.get_snapshot.return_value = {"available": True, "data": {"nav": 100000}}
    portfolio_client.get_exposure.return_value = {"available": True, "data": {}}
    portfolio_client.get_positions.return_value = {"available": True, "data": []}

    req = PortfolioReviewRequest(include_positions=True)
    context, warnings = await build_portfolio_review_context(req, portfolio_client)

    assert context["positions"]["available"] is True
    assert warnings == []


@pytest.mark.asyncio
async def test_portfolio_review_context_skips_positions_when_not_requested():
    portfolio_client = AsyncMock()
    portfolio_client.get_snapshot.return_value = {"available": True, "data": {}}
    portfolio_client.get_exposure.return_value = {"available": True, "data": {}}

    req = PortfolioReviewRequest(include_positions=False)
    context, warnings = await build_portfolio_review_context(req, portfolio_client)

    assert context["positions"] is None
    portfolio_client.get_positions.assert_not_called()


@pytest.mark.asyncio
async def test_risk_explanation_context_uses_symbol_endpoint_when_symbol_given():
    risk_client = AsyncMock()
    risk_client.get_symbol_risk.return_value = {"available": True, "data": {}}
    risk_client.get_recent_risk_events.return_value = {"available": True, "data": []}

    req = RiskExplanationRequest(symbol="TCS")
    context, warnings = await build_risk_explanation_context(req, risk_client)

    risk_client.get_symbol_risk.assert_awaited_once_with("TCS")
    risk_client.get_risk_snapshot.assert_not_called()
    assert warnings == []


@pytest.mark.asyncio
async def test_market_summary_context_aggregates_multiple_symbols():
    market_data_client = AsyncMock()
    market_data_client.get_ltp.return_value = {"available": True, "data": {"ltp": 100.0}}
    market_data_client.get_recent_history.return_value = {"available": True, "data": {"candles": []}}

    req = MarketSummaryRequest(symbols=["RELIANCE", "TCS"])
    context, warnings = await build_market_summary_context(req, market_data_client)

    assert set(context["per_symbol"].keys()) == {"RELIANCE", "TCS"}
    assert warnings == []
    assert market_data_client.get_ltp.await_count == 2
