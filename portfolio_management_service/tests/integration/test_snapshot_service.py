"""
Integration tests for snapshot_service.py.

All DB/MTM calls are mocked at the module where they are imported,
not at the originating module (Python mock best practice).
"""
from __future__ import annotations

from decimal import Decimal
from unittest.mock import AsyncMock, patch

import pytest

from app.models.domain import PerformanceMetrics, PerformanceWindow, Position, PortfolioSnapshot


def _make_position(symbol: str, qty: int, avg_cost: float, market_price: float) -> Position:
    p = Position(symbol=symbol, net_quantity=qty, avg_cost_inr=Decimal(str(avg_cost)))
    p.recompute_from_mtm(Decimal(str(market_price)))
    return p


_MOCK_CONFIG = {"initial_capital_inr": "1000000", "cash_balance_inr": "1000000"}


class TestBuildSnapshot:
    @pytest.mark.asyncio
    async def test_build_snapshot_empty_portfolio(self):
        from app.services.snapshot_service import build_snapshot

        mock_perf = PerformanceMetrics(window=PerformanceWindow.DAYS_30)

        with (
            patch("app.services.snapshot_service.refresh_all_positions",
                  new_callable=AsyncMock, return_value=[]),
            patch("app.services.snapshot_service.repo") as mock_repo,
            patch("app.services.snapshot_service.compute_performance",
                  new_callable=AsyncMock, return_value=mock_perf),
            # Also patch inside mtm_service since get_portfolio_totals uses repo there
            patch("app.services.mtm_service.repo") as mock_mtm_repo,
        ):
            mock_repo.list_positions = AsyncMock(return_value=[])
            mock_mtm_repo.get_portfolio_config = AsyncMock(return_value=_MOCK_CONFIG)

            snap = await build_snapshot(refresh_mtm=True)

        assert isinstance(snap, PortfolioSnapshot)
        assert snap.open_position_count == 0
        assert snap.positions == []
        assert snap.equity_value_inr == Decimal("0")
        assert snap.cash_balance_inr == Decimal("1000000")

    @pytest.mark.asyncio
    async def test_build_snapshot_with_positions(self):
        from app.services.snapshot_service import build_snapshot

        positions = [
            _make_position("RELIANCE", 100, 1000.0, 1100.0),
            _make_position("INFY", 50, 1500.0, 1600.0),
        ]
        mock_perf = PerformanceMetrics(window=PerformanceWindow.DAYS_30)

        with (
            patch("app.services.snapshot_service.refresh_all_positions",
                  new_callable=AsyncMock, return_value=positions),
            patch("app.services.snapshot_service.repo") as mock_repo,
            patch("app.services.snapshot_service.compute_performance",
                  new_callable=AsyncMock, return_value=mock_perf),
            patch("app.services.mtm_service.repo") as mock_mtm_repo,
        ):
            mock_repo.list_positions = AsyncMock(return_value=positions)
            mock_mtm_repo.get_portfolio_config = AsyncMock(
                return_value={"initial_capital_inr": "1000000", "cash_balance_inr": "800000"}
            )

            snap = await build_snapshot(refresh_mtm=True)

        # RELIANCE: 1100*100=110,000; INFY: 1600*50=80,000 → equity=190,000
        assert snap.equity_value_inr == Decimal("190000.00")
        assert snap.open_position_count == 2
        assert len(snap.positions) == 2

    @pytest.mark.asyncio
    async def test_position_summaries_have_weights(self):
        from app.services.snapshot_service import build_snapshot

        positions = [_make_position("RELIANCE", 100, 1000.0, 1000.0)]
        mock_perf = PerformanceMetrics(window=PerformanceWindow.DAYS_30)

        with (
            patch("app.services.snapshot_service.refresh_all_positions",
                  new_callable=AsyncMock, return_value=positions),
            patch("app.services.snapshot_service.repo") as mock_repo,
            patch("app.services.snapshot_service.compute_performance",
                  new_callable=AsyncMock, return_value=mock_perf),
            patch("app.services.mtm_service.repo") as mock_mtm_repo,
        ):
            mock_repo.list_positions = AsyncMock(return_value=positions)
            mock_mtm_repo.get_portfolio_config = AsyncMock(
                return_value={"initial_capital_inr": "200000", "cash_balance_inr": "100000"}
            )

            snap = await build_snapshot(refresh_mtm=True)

        # equity=100,000; cash=100,000; total=200,000 → RELIANCE weight=50%
        assert len(snap.positions) == 1
        assert snap.positions[0].weight_pct == pytest.approx(50.0, rel=0.01)

    @pytest.mark.asyncio
    async def test_perf_failure_does_not_crash_snapshot(self):
        """If performance computation fails, snapshot still returns with perf_30d=None."""
        from app.services.snapshot_service import build_snapshot

        with (
            patch("app.services.snapshot_service.refresh_all_positions",
                  new_callable=AsyncMock, return_value=[]),
            patch("app.services.snapshot_service.repo") as mock_repo,
            patch("app.services.snapshot_service.compute_performance",
                  new_callable=AsyncMock, side_effect=RuntimeError("DB error")),
            patch("app.services.mtm_service.repo") as mock_mtm_repo,
        ):
            mock_repo.list_positions = AsyncMock(return_value=[])
            mock_mtm_repo.get_portfolio_config = AsyncMock(return_value=_MOCK_CONFIG)

            snap = await build_snapshot(refresh_mtm=True)

        assert snap.performance_30d is None
        assert isinstance(snap, PortfolioSnapshot)

    @pytest.mark.asyncio
    async def test_build_and_persist_calls_insert(self):
        from app.services.snapshot_service import build_and_persist

        mock_snap = PortfolioSnapshot(
            initial_capital_inr=Decimal("1000000"),
            cash_balance_inr=Decimal("1000000"),
            equity_value_inr=Decimal("0"),
            total_value_inr=Decimal("1000000"),
        )

        with (
            patch("app.services.snapshot_service.build_snapshot",
                  new_callable=AsyncMock, return_value=mock_snap),
            patch("app.services.snapshot_service.persist_snapshot",
                  new_callable=AsyncMock) as mock_persist,
        ):
            result = await build_and_persist(refresh_mtm=False)

        mock_persist.assert_called_once_with(mock_snap)
        assert result == mock_snap
