"""
Unit tests for mtm_service.py — mark-to-market logic and portfolio totals.
"""
from __future__ import annotations

from decimal import Decimal
from unittest.mock import AsyncMock, patch

import pytest

from app.models.domain import Position


def _pos(symbol: str, qty: int, avg_cost: float, market_price: float | None = None) -> Position:
    p = Position(
        symbol=symbol,
        net_quantity=qty,
        avg_cost_inr=Decimal(str(avg_cost)),
    )
    if market_price is not None:
        p.recompute_from_mtm(Decimal(str(market_price)))
    return p


class TestGetPortfolioTotals:
    @pytest.mark.asyncio
    async def test_empty_positions(self):
        from app.services.mtm_service import get_portfolio_totals

        with patch("app.services.mtm_service.repo") as mock_repo:
            mock_repo.get_portfolio_config = AsyncMock(
                return_value={"initial_capital_inr": "1000000", "cash_balance_inr": "1000000"}
            )
            totals = await get_portfolio_totals([])

        assert totals["open_position_count"] == 0
        assert totals["equity_value_inr"] == Decimal("0")
        assert totals["total_value_inr"] == Decimal("1000000")

    @pytest.mark.asyncio
    async def test_single_profitable_position(self):
        from app.services.mtm_service import get_portfolio_totals

        pos = _pos("RELIANCE", qty=100, avg_cost=1000.0, market_price=1200.0)

        with patch("app.services.mtm_service.repo") as mock_repo:
            mock_repo.get_portfolio_config = AsyncMock(
                return_value={"initial_capital_inr": "1000000", "cash_balance_inr": "880000"}
            )
            totals = await get_portfolio_totals([pos])

        # Equity = 1200 * 100 = 120,000; cash = 880,000 → total = 1,000,000
        assert totals["equity_value_inr"] == Decimal("120000.00")
        assert totals["total_value_inr"] == Decimal("1000000.00")
        assert totals["open_position_count"] == 1

    @pytest.mark.asyncio
    async def test_gross_exposure_is_sum_of_absolute_values(self):
        from app.services.mtm_service import get_portfolio_totals

        pos1 = _pos("RELIANCE", qty=100, avg_cost=1000.0, market_price=1100.0)
        pos2 = _pos("INFY", qty=200, avg_cost=1500.0, market_price=1400.0)

        with patch("app.services.mtm_service.repo") as mock_repo:
            mock_repo.get_portfolio_config = AsyncMock(
                return_value={"initial_capital_inr": "1000000", "cash_balance_inr": "500000"}
            )
            totals = await get_portfolio_totals([pos1, pos2])

        # pos1: 1100*100 = 110,000; pos2: 1400*200 = 280,000
        assert totals["gross_exposure_inr"] == Decimal("390000.00")

    @pytest.mark.asyncio
    async def test_total_return_pct(self):
        from app.services.mtm_service import get_portfolio_totals

        pos = _pos("TCS", qty=100, avg_cost=3000.0, market_price=3300.0)

        with patch("app.services.mtm_service.repo") as mock_repo:
            mock_repo.get_portfolio_config = AsyncMock(
                return_value={"initial_capital_inr": "1000000", "cash_balance_inr": "700000"}
            )
            totals = await get_portfolio_totals([pos])

        # total_value = 700,000 + 330,000 = 1,030,000
        # pnl = 1,030,000 - 1,000,000 = 30,000
        # return_pct = 30,000 / 1,000,000 * 100 = 3.0%
        assert totals["total_return_pct"] == pytest.approx(3.0, rel=0.01)

    @pytest.mark.asyncio
    async def test_zero_initial_capital_no_divide_by_zero(self):
        from app.services.mtm_service import get_portfolio_totals

        with patch("app.services.mtm_service.repo") as mock_repo:
            mock_repo.get_portfolio_config = AsyncMock(
                return_value={"initial_capital_inr": "0", "cash_balance_inr": "0"}
            )
            totals = await get_portfolio_totals([])

        assert totals["total_return_pct"] == 0.0


class TestRefreshAllPositions:
    @pytest.mark.asyncio
    async def test_no_positions_returns_empty(self):
        from app.services.mtm_service import refresh_all_positions

        with (
            patch("app.services.mtm_service.repo") as mock_repo,
            patch("app.services.mtm_service.market_data_client"),
        ):
            mock_repo.list_positions = AsyncMock(return_value=[])
            result = await refresh_all_positions()

        assert result == []

    @pytest.mark.asyncio
    async def test_price_fetch_failure_uses_stale_price(self):
        """When LTP unavailable, position is updated with last known price."""
        from app.services.mtm_service import refresh_all_positions

        pos = _pos("RELIANCE", qty=100, avg_cost=1000.0, market_price=1100.0)

        with (
            patch("app.services.mtm_service.repo") as mock_repo,
            patch("app.services.mtm_service.market_data_client") as mock_md,
        ):
            mock_repo.list_positions = AsyncMock(return_value=[pos])
            mock_repo.get_portfolio_config = AsyncMock(
                return_value={"initial_capital_inr": "1000000", "cash_balance_inr": "900000"}
            )
            mock_repo.update_position_mtm = AsyncMock()
            mock_md.get_last_price = AsyncMock(return_value=None)  # unavailable

            result = await refresh_all_positions()

        assert len(result) == 1
        # Should still have been called with stale price
        mock_repo.update_position_mtm.assert_called_once()

    @pytest.mark.asyncio
    async def test_price_fetch_success_updates_mtm(self):
        from app.services.mtm_service import refresh_all_positions

        pos = _pos("INFY", qty=50, avg_cost=1500.0, market_price=1500.0)

        with (
            patch("app.services.mtm_service.repo") as mock_repo,
            patch("app.services.mtm_service.market_data_client") as mock_md,
        ):
            mock_repo.list_positions = AsyncMock(return_value=[pos])
            mock_repo.get_portfolio_config = AsyncMock(
                return_value={"initial_capital_inr": "1000000", "cash_balance_inr": "900000"}
            )
            mock_repo.update_position_mtm = AsyncMock()
            mock_md.get_last_price = AsyncMock(return_value=1600.0)

            result = await refresh_all_positions()

        assert len(result) == 1
        mock_repo.update_position_mtm.assert_called_once_with(
            symbol="INFY",
            market_price_inr=Decimal("1600.0"),
            market_value_inr=pytest.approx(Decimal("80000.0")),
            unrealized_pnl_inr=pytest.approx(Decimal("5000.0")),  # (1600-1500)*50
            total_pnl_inr=pytest.approx(Decimal("5000.0")),
            day_pnl_inr=pytest.approx(Decimal("5000.0")),
        )
