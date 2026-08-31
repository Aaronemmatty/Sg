"""
Unit tests for domain models (domain.py).

Validates Pydantic v2 model construction, field validators,
computed properties, and serialization.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import Decimal

import pytest

from app.models.domain import (
    ExecutionEvent,
    ExecutionEventType,
    Lot,
    LotStatus,
    PerformanceMetrics,
    PerformanceWindow,
    PortfolioEvent,
    PortfolioEventType,
    PortfolioSnapshot,
    Position,
    PositionSummary,
    TradeAction,
)


class TestExecutionEvent:
    def _base(self, **kwargs) -> dict:
        return {
            "event_type": "ORDER_FILLED",
            "order_id": str(uuid.uuid4()),
            "intent_id": str(uuid.uuid4()),
            "correlation_id": str(uuid.uuid4()),
            "symbol": "reliance",
            "action": "BUY",
            "state": "FILLED",
            "filled_quantity": 100,
            "avg_fill_price_inr": 1234.5,
            **kwargs,
        }

    def test_symbol_uppercased_by_validator(self):
        event = ExecutionEvent.model_validate(self._base(symbol="reliance"))
        assert event.symbol == "RELIANCE"

    def test_symbol_already_upper_passes(self):
        event = ExecutionEvent.model_validate(self._base(symbol="NIFTY"))
        assert event.symbol == "NIFTY"

    def test_is_fill_event_for_filled(self):
        event = ExecutionEvent.model_validate(self._base(event_type="ORDER_FILLED"))
        assert event.is_fill_event is True

    def test_is_fill_event_for_partially_filled(self):
        event = ExecutionEvent.model_validate(self._base(event_type="ORDER_PARTIALLY_FILLED"))
        assert event.is_fill_event is True

    def test_is_not_fill_event_for_submitted(self):
        event = ExecutionEvent.model_validate(self._base(event_type="ORDER_SUBMITTED"))
        assert event.is_fill_event is False

    def test_is_not_fill_event_for_failed(self):
        event = ExecutionEvent.model_validate(self._base(event_type="ORDER_FAILED"))
        assert event.is_fill_event is False

    def test_optional_fields_have_defaults(self):
        event = ExecutionEvent.model_validate(self._base())
        assert event.slippage_bps is None
        assert event.broker_order_id is None
        assert event.reason is None
        assert event.filled_quantity == 100

    def test_serialization_round_trip(self):
        event = ExecutionEvent.model_validate(self._base())
        json_str = event.model_dump_json()
        restored = ExecutionEvent.model_validate_json(json_str)
        assert restored.symbol == event.symbol
        assert restored.order_id == event.order_id


class TestPosition:
    def test_is_flat_when_zero_quantity(self):
        pos = Position(symbol="RELIANCE", net_quantity=0)
        assert pos.is_flat is True

    def test_is_not_flat_when_nonzero(self):
        pos = Position(symbol="RELIANCE", net_quantity=50)
        assert pos.is_flat is False

    def test_recompute_sets_last_mtm_at(self):
        pos = Position(symbol="INFY", net_quantity=100, avg_cost_inr=Decimal("1500"))
        assert pos.last_mtm_at is None
        pos.recompute_from_mtm(Decimal("1600"))
        assert pos.last_mtm_at is not None

    def test_recompute_market_value(self):
        pos = Position(symbol="TCS", net_quantity=200, avg_cost_inr=Decimal("3000"))
        pos.recompute_from_mtm(Decimal("3500"))
        assert pos.market_value_inr == Decimal("700000")  # 3500 * 200

    def test_recompute_unrealized_pnl(self):
        pos = Position(symbol="HDFC", net_quantity=100, avg_cost_inr=Decimal("1000"))
        pos.recompute_from_mtm(Decimal("1050"))
        assert pos.unrealized_pnl_inr == Decimal("5000")  # (1050-1000)*100

    def test_default_decimal_fields_are_zero(self):
        pos = Position(symbol="WIPRO")
        assert pos.avg_cost_inr == Decimal("0")
        assert pos.realized_pnl_inr == Decimal("0")
        assert pos.unrealized_pnl_inr == Decimal("0")


class TestLot:
    def test_default_status_is_open(self):
        lot = Lot(
            symbol="RELIANCE",
            order_id=uuid.uuid4(),
            execution_event_id=uuid.uuid4(),
            original_quantity=100,
            remaining_quantity=100,
            cost_price_inr=Decimal("1000"),
        )
        assert lot.status == LotStatus.OPEN

    def test_lot_id_auto_generated(self):
        lot = Lot(
            symbol="RELIANCE",
            order_id=uuid.uuid4(),
            execution_event_id=uuid.uuid4(),
            original_quantity=100,
            remaining_quantity=100,
            cost_price_inr=Decimal("1000"),
        )
        assert lot.lot_id is not None
        assert isinstance(lot.lot_id, uuid.UUID)

    def test_opened_at_auto_generated(self):
        lot = Lot(
            symbol="TCS",
            order_id=uuid.uuid4(),
            execution_event_id=uuid.uuid4(),
            original_quantity=50,
            remaining_quantity=50,
            cost_price_inr=Decimal("3000"),
        )
        assert lot.opened_at is not None


class TestPortfolioSnapshot:
    def test_snapshot_id_auto_generated(self):
        snap = PortfolioSnapshot(
            initial_capital_inr=Decimal("1000000"),
            cash_balance_inr=Decimal("500000"),
            equity_value_inr=Decimal("600000"),
            total_value_inr=Decimal("1100000"),
        )
        assert snap.snapshot_id is not None

    def test_positions_default_empty(self):
        snap = PortfolioSnapshot(
            initial_capital_inr=Decimal("0"),
            cash_balance_inr=Decimal("0"),
            equity_value_inr=Decimal("0"),
            total_value_inr=Decimal("0"),
        )
        assert snap.positions == []

    def test_json_serialization(self):
        snap = PortfolioSnapshot(
            initial_capital_inr=Decimal("1000000"),
            cash_balance_inr=Decimal("200000"),
            equity_value_inr=Decimal("850000"),
            total_value_inr=Decimal("1050000"),
            total_return_pct=5.0,
            open_position_count=3,
        )
        data = snap.model_dump(mode="json")
        assert data["total_return_pct"] == 5.0
        assert data["open_position_count"] == 3


class TestPerformanceMetrics:
    def test_defaults_to_zero_metrics(self):
        metrics = PerformanceMetrics(window=PerformanceWindow.DAYS_30)
        assert metrics.total_return_pct == 0.0
        assert metrics.sharpe_ratio is None
        assert metrics.max_drawdown_pct == 0.0
        assert metrics.win_rate_pct == 0.0
        assert metrics.alpha is None
        assert metrics.beta is None

    def test_window_field_preserved(self):
        m = PerformanceMetrics(window=PerformanceWindow.INCEPTION)
        assert m.window == PerformanceWindow.INCEPTION

    def test_computed_at_auto_populated(self):
        m = PerformanceMetrics(window=PerformanceWindow.DAYS_7)
        assert m.computed_at is not None
