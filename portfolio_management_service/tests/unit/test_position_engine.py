"""
Unit tests for position_engine.py — FIFO lot management and P&L calculation.

All DB calls are mocked; tests exercise only the pure calculation logic
exposed through the engine functions.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.domain import (
    ExecutionEvent,
    ExecutionEventType,
    Lot,
    LotStatus,
    Position,
    TradeAction,
)


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _make_fill_event(
    action: TradeAction,
    filled_quantity: int,
    avg_fill_price_inr: float,
    event_type: str = ExecutionEventType.ORDER_FILLED,
    symbol: str = "RELIANCE",
) -> ExecutionEvent:
    return ExecutionEvent(
        event_type=event_type,
        order_id=uuid.uuid4(),
        intent_id=uuid.uuid4(),
        correlation_id=uuid.uuid4(),
        symbol=symbol,
        action=action,
        state="FILLED",
        filled_quantity=filled_quantity,
        avg_fill_price_inr=avg_fill_price_inr,
        emitted_at=datetime.now(timezone.utc),
    )


def _make_lot(
    symbol: str,
    quantity: int,
    cost_price: float,
    remaining: int | None = None,
    status: LotStatus = LotStatus.OPEN,
) -> Lot:
    return Lot(
        symbol=symbol,
        order_id=uuid.uuid4(),
        execution_event_id=uuid.uuid4(),
        original_quantity=quantity,
        remaining_quantity=remaining if remaining is not None else quantity,
        cost_price_inr=Decimal(str(cost_price)),
        status=status,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Tests: avg cost calculation
# ─────────────────────────────────────────────────────────────────────────────

class TestAvgCostCalculation:
    """Validate weighted average cost computation on sequential buys."""

    def test_single_buy_avg_cost(self):
        """Single buy: avg cost = fill price."""
        lots = [_make_lot("RELIANCE", quantity=100, cost_price=1000.0)]
        total_cost = sum(Decimal(str(l.remaining_quantity)) * l.cost_price_inr for l in lots)
        total_qty = sum(l.remaining_quantity for l in lots)
        avg = total_cost / Decimal(str(total_qty))
        assert avg == Decimal("1000.0")

    def test_two_buys_weighted_avg(self):
        """100 @ 1000 + 200 @ 1100 → avg = (100*1000 + 200*1100) / 300 = 1066.67"""
        lots = [
            _make_lot("RELIANCE", quantity=100, cost_price=1000.0),
            _make_lot("RELIANCE", quantity=200, cost_price=1100.0),
        ]
        total_cost = sum(Decimal(str(l.remaining_quantity)) * l.cost_price_inr for l in lots)
        total_qty = sum(l.remaining_quantity for l in lots)
        avg = (total_cost / Decimal(str(total_qty))).quantize(Decimal("0.01"))
        assert avg == Decimal("1066.67")

    def test_three_buys_at_same_price(self):
        """All lots at same price: avg = that price."""
        lots = [_make_lot("INFY", quantity=50, cost_price=1500.0) for _ in range(3)]
        total_cost = sum(Decimal(str(l.remaining_quantity)) * l.cost_price_inr for l in lots)
        total_qty = sum(l.remaining_quantity for l in lots)
        avg = total_cost / Decimal(str(total_qty))
        assert avg == Decimal("1500.0")


# ─────────────────────────────────────────────────────────────────────────────
# Tests: realized P&L calculation (FIFO)
# ─────────────────────────────────────────────────────────────────────────────

class TestRealizedPnL:
    """Validate FIFO realized P&L on sells against known lots."""

    def _compute_realized(
        self,
        lots: list[Lot],
        sell_qty: int,
        sell_price: float,
    ) -> tuple[Decimal, list[tuple[uuid.UUID, int]]]:
        """Simulate FIFO sell logic without hitting the DB."""
        sell_price_d = Decimal(str(sell_price))
        remaining = sell_qty
        total_realized = Decimal("0")
        consumed: list[tuple[uuid.UUID, int]] = []

        for lot in lots:
            if remaining <= 0:
                break
            take = min(lot.remaining_quantity, remaining)
            realized = (sell_price_d - lot.cost_price_inr) * Decimal(str(take))
            total_realized += realized
            consumed.append((lot.lot_id, take))
            remaining -= take

        return total_realized, consumed

    def test_full_lot_sell_profit(self):
        """Buy 100 @ 1000, sell 100 @ 1200 → realized = +20,000."""
        lot = _make_lot("RELIANCE", quantity=100, cost_price=1000.0)
        realized, consumed = self._compute_realized([lot], sell_qty=100, sell_price=1200.0)
        assert realized == Decimal("20000.00")
        assert consumed == [(lot.lot_id, 100)]

    def test_full_lot_sell_loss(self):
        """Buy 100 @ 1200, sell 100 @ 1000 → realized = -20,000."""
        lot = _make_lot("RELIANCE", quantity=100, cost_price=1200.0)
        realized, _ = self._compute_realized([lot], sell_qty=100, sell_price=1000.0)
        assert realized == Decimal("-20000.00")

    def test_partial_lot_sell(self):
        """Buy 100 @ 1000, sell 40 → realized on 40 shares only."""
        lot = _make_lot("RELIANCE", quantity=100, cost_price=1000.0)
        realized, consumed = self._compute_realized([lot], sell_qty=40, sell_price=1100.0)
        assert realized == Decimal("4000.00")  # (1100-1000) * 40
        assert consumed == [(lot.lot_id, 40)]

    def test_fifo_consumes_oldest_lot_first(self):
        """Two lots at different prices; sell consumes oldest first."""
        lot1 = _make_lot("INFY", quantity=50, cost_price=1500.0)  # opened first
        lot2 = _make_lot("INFY", quantity=50, cost_price=1600.0)  # opened second
        realized, consumed = self._compute_realized([lot1, lot2], sell_qty=50, sell_price=1700.0)
        # Should consume lot1 entirely: (1700-1500) * 50 = 10,000
        assert realized == Decimal("10000.00")
        assert consumed[0][0] == lot1.lot_id
        assert consumed[0][1] == 50
        assert len(consumed) == 1

    def test_fifo_spans_multiple_lots(self):
        """Sell qty spans across two lots."""
        lot1 = _make_lot("TCS", quantity=30, cost_price=3000.0)
        lot2 = _make_lot("TCS", quantity=70, cost_price=3200.0)
        # Sell 50: consume all of lot1 (30) + 20 from lot2
        realized, consumed = self._compute_realized([lot1, lot2], sell_qty=50, sell_price=3500.0)
        realized_lot1 = (Decimal("3500") - Decimal("3000")) * 30  # 15,000
        realized_lot2 = (Decimal("3500") - Decimal("3200")) * 20  # 6,000
        expected = realized_lot1 + realized_lot2                   # 21,000
        assert realized == expected
        assert consumed[0] == (lot1.lot_id, 30)
        assert consumed[1] == (lot2.lot_id, 20)

    def test_breakeven_trade(self):
        """Buy and sell at same price → realized = 0."""
        lot = _make_lot("HDFC", quantity=100, cost_price=1500.0)
        realized, _ = self._compute_realized([lot], sell_qty=100, sell_price=1500.0)
        assert realized == Decimal("0.00")


# ─────────────────────────────────────────────────────────────────────────────
# Tests: Position MTM recomputation
# ─────────────────────────────────────────────────────────────────────────────

class TestPositionMTM:
    def test_recompute_long_position(self):
        pos = Position(
            symbol="RELIANCE",
            net_quantity=100,
            avg_cost_inr=Decimal("1000.00"),
            realized_pnl_inr=Decimal("0"),
        )
        pos.recompute_from_mtm(Decimal("1200.00"))

        assert pos.market_price_inr == Decimal("1200.00")
        assert pos.market_value_inr == Decimal("120000.00")  # 1200 * 100
        assert pos.unrealized_pnl_inr == Decimal("20000.00")  # (1200-1000)*100
        assert pos.total_pnl_inr == Decimal("20000.00")       # realized=0 + unrealized=20000
        assert pos.last_mtm_at is not None

    def test_recompute_loss_position(self):
        pos = Position(
            symbol="INFY",
            net_quantity=50,
            avg_cost_inr=Decimal("1600.00"),
        )
        pos.recompute_from_mtm(Decimal("1400.00"))
        assert pos.unrealized_pnl_inr == Decimal("-10000.00")  # (1400-1600)*50

    def test_flat_position_zero_unrealized(self):
        pos = Position(symbol="TCS", net_quantity=0, avg_cost_inr=Decimal("3000.00"))
        pos.recompute_from_mtm(Decimal("3500.00"))
        assert pos.unrealized_pnl_inr == Decimal("0")
        assert pos.market_value_inr == Decimal("0")

    def test_total_pnl_includes_realized(self):
        pos = Position(
            symbol="WIPRO",
            net_quantity=100,
            avg_cost_inr=Decimal("400.00"),
            realized_pnl_inr=Decimal("5000.00"),  # from a prior sell
        )
        pos.recompute_from_mtm(Decimal("450.00"))
        # unrealized: (450-400)*100 = 5000
        assert pos.unrealized_pnl_inr == Decimal("5000.00")
        assert pos.total_pnl_inr == Decimal("10000.00")  # 5000 realized + 5000 unrealized


# ─────────────────────────────────────────────────────────────────────────────
# Tests: ExecutionEvent validation
# ─────────────────────────────────────────────────────────────────────────────

class TestExecutionEvent:
    def test_symbol_uppercased(self):
        event = _make_fill_event(TradeAction.BUY, 100, 1000.0, symbol="reliance")
        assert event.symbol == "RELIANCE"

    def test_is_fill_event_true_for_filled(self):
        event = _make_fill_event(TradeAction.BUY, 100, 1000.0, event_type=ExecutionEventType.ORDER_FILLED)
        assert event.is_fill_event is True

    def test_is_fill_event_true_for_partial(self):
        event = _make_fill_event(TradeAction.BUY, 50, 1000.0, event_type=ExecutionEventType.ORDER_PARTIALLY_FILLED)
        assert event.is_fill_event is True

    def test_is_fill_event_false_for_submitted(self):
        event = _make_fill_event(TradeAction.BUY, 0, 0.0, event_type=ExecutionEventType.ORDER_SUBMITTED)
        assert event.is_fill_event is False

    def test_is_fill_event_false_for_rejected(self):
        event = _make_fill_event(TradeAction.SELL, 0, 0.0, event_type=ExecutionEventType.ORDER_REJECTED)
        assert event.is_fill_event is False


# ─────────────────────────────────────────────────────────────────────────────
# Tests: Lot status transitions
# ─────────────────────────────────────────────────────────────────────────────

class TestLotStatus:
    def test_lot_is_open_by_default(self):
        lot = _make_lot("RELIANCE", quantity=100, cost_price=1000.0)
        assert lot.status == LotStatus.OPEN
        assert lot.remaining_quantity == 100

    def test_lot_becomes_partially_closed(self):
        lot = _make_lot("RELIANCE", quantity=100, cost_price=1000.0)
        lot.remaining_quantity -= 40
        lot.status = LotStatus.PARTIALLY_CLOSED
        assert lot.status == LotStatus.PARTIALLY_CLOSED
        assert lot.remaining_quantity == 60

    def test_lot_becomes_closed_at_zero(self):
        lot = _make_lot("RELIANCE", quantity=100, cost_price=1000.0)
        lot.remaining_quantity = 0
        lot.status = LotStatus.CLOSED
        assert lot.status == LotStatus.CLOSED


# ─────────────────────────────────────────────────────────────────────────────
# Tests: apply_fill integration (with mocked DB)
# ─────────────────────────────────────────────────────────────────────────────

class TestApplyFillMocked:
    """
    Integration-style tests that mock the DB layer entirely.
    Validates that apply_fill calls the correct repository methods
    with the correct arguments.
    """

    @pytest.mark.asyncio
    async def test_apply_buy_fill_creates_lot_and_upserts_position(self):
        event = _make_fill_event(TradeAction.BUY, filled_quantity=100, avg_fill_price_inr=1000.0)
        existing_pos = Position(symbol="RELIANCE", net_quantity=0)
        new_lot = _make_lot("RELIANCE", quantity=100, cost_price=1000.0)

        mock_conn = AsyncMock()
        mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_conn.__aexit__ = AsyncMock(return_value=False)
        mock_conn.transaction = MagicMock(return_value=mock_conn)

        with (
            patch("app.services.position_engine.pool") as mock_pool,
            patch("app.services.position_engine.repo") as mock_repo,
        ):
            mock_pool.acquire.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
            mock_pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)
            mock_conn.transaction.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
            mock_conn.transaction.return_value.__aexit__ = AsyncMock(return_value=False)

            mock_repo.get_position = AsyncMock(return_value=existing_pos)
            mock_repo.insert_lot = AsyncMock()
            mock_repo.get_open_lots = AsyncMock(return_value=[new_lot])
            mock_repo.upsert_position = AsyncMock()
            mock_repo.insert_trade_ledger_entry = AsyncMock()

            from app.services.position_engine import apply_fill
            result = await apply_fill(event)

        mock_repo.insert_lot.assert_called_once()
        mock_repo.upsert_position.assert_called_once()
        mock_repo.insert_trade_ledger_entry.assert_called_once()
        assert result.net_quantity == 100
        assert result.avg_cost_inr == Decimal("1000.00")

    @pytest.mark.asyncio
    async def test_apply_sell_fill_computes_realized_pnl(self):
        event = _make_fill_event(TradeAction.SELL, filled_quantity=100, avg_fill_price_inr=1200.0)
        existing_pos = Position(
            symbol="RELIANCE",
            net_quantity=100,
            avg_cost_inr=Decimal("1000.00"),
        )
        open_lot = _make_lot("RELIANCE", quantity=100, cost_price=1000.0)

        mock_conn = AsyncMock()
        # transaction() must return an async context manager, not a coroutine
        mock_txn = MagicMock()
        mock_txn.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_txn.__aexit__ = AsyncMock(return_value=False)
        mock_conn.transaction = MagicMock(return_value=mock_txn)

        with (
            patch("app.services.position_engine.pool") as mock_pool,
            patch("app.services.position_engine.repo") as mock_repo,
        ):
            mock_pool.acquire.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
            mock_pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)

            mock_repo.get_position = AsyncMock(return_value=existing_pos)
            mock_repo.get_open_lots = AsyncMock(return_value=[open_lot])
            mock_repo.insert_lot_consumption = AsyncMock()
            mock_repo.update_lot = AsyncMock()
            mock_repo.upsert_position = AsyncMock()
            mock_repo.insert_trade_ledger_entry = AsyncMock()

            from app.services.position_engine import apply_fill
            result = await apply_fill(event)

        # (1200 - 1000) * 100 = 20,000 realized
        assert result.realized_pnl_inr == Decimal("20000.00")
        assert result.net_quantity == 0
        mock_repo.insert_lot_consumption.assert_called_once()
        mock_repo.update_lot.assert_called_once()

    @pytest.mark.asyncio
    async def test_apply_fill_raises_on_missing_price(self):
        event = ExecutionEvent(
            event_type=ExecutionEventType.ORDER_FILLED,
            order_id=uuid.uuid4(),
            intent_id=uuid.uuid4(),
            correlation_id=uuid.uuid4(),
            symbol="RELIANCE",
            action=TradeAction.BUY,
            state="FILLED",
            filled_quantity=100,
            avg_fill_price_inr=None,  # missing price
        )
        from app.services.position_engine import apply_fill
        with pytest.raises(ValueError, match="no fill price"):
            await apply_fill(event)
