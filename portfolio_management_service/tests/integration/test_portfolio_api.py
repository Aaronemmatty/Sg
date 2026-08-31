"""
Integration tests for portfolio REST API endpoints.

Tests cover:
  - GET /api/v1/portfolio/snapshot
  - GET /api/v1/portfolio/positions
  - GET /api/v1/portfolio/positions/{symbol}
  - GET /api/v1/portfolio/exposure
  - GET /api/v1/portfolio/lots/{symbol}
  - GET /api/v1/performance/{window}
  - GET /api/v1/performance/summary
  - GET /api/v1/ledger/trades
  - GET /api/v1/ledger/snapshots
  - GET /api/v1/ledger/snapshots/latest
  - GET /health
"""
from __future__ import annotations

import uuid
from decimal import Decimal
from unittest.mock import AsyncMock, patch, MagicMock

import pytest

from app.models.domain import (
    PerformanceMetrics,
    PerformanceWindow,
    Position,
    PortfolioSnapshot,
)


# ─────────────────────────────────────────────────────────────────────────────
# Health
# ─────────────────────────────────────────────────────────────────────────────

class TestHealth:
    @pytest.mark.asyncio
    async def test_health_ok(self, client):
        with patch("app.api.v1.endpoints.health.pool") as mock_pool:
            mock_conn = AsyncMock()
            mock_conn.fetchval = AsyncMock(return_value=1)
            mock_pool.acquire.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
            mock_pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)

            resp = await client.get("/api/v1/health")

        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["service"] == "portfolio_management_service"

    @pytest.mark.asyncio
    async def test_health_degraded_on_db_error(self, client):
        with patch("app.api.v1.endpoints.health.pool") as mock_pool:
            mock_pool.acquire.side_effect = Exception("DB down")
            resp = await client.get("/api/v1/health")

        assert resp.status_code == 200
        assert resp.json()["status"] == "degraded"

    @pytest.mark.asyncio
    async def test_root_returns_service_name(self, client):
        resp = await client.get("/api/v1/")
        assert resp.status_code == 200
        assert "portfolio_management_service" in resp.json()["service"]


# ─────────────────────────────────────────────────────────────────────────────
# Portfolio snapshot
# ─────────────────────────────────────────────────────────────────────────────

class TestPortfolioSnapshot:
    def _make_snapshot(self) -> PortfolioSnapshot:
        return PortfolioSnapshot(
            initial_capital_inr=Decimal("1000000"),
            cash_balance_inr=Decimal("800000"),
            equity_value_inr=Decimal("250000"),
            total_value_inr=Decimal("1050000"),
            day_pnl_inr=Decimal("5000"),
            total_pnl_inr=Decimal("50000"),
            total_return_pct=5.0,
            gross_exposure_pct=23.8,
            open_position_count=2,
        )

    @pytest.mark.asyncio
    async def test_snapshot_returns_200(self, client):
        snap = self._make_snapshot()
        with patch("app.api.v1.endpoints.portfolio.build_snapshot", new_callable=AsyncMock) as m:
            m.return_value = snap
            resp = await client.get("/api/v1/portfolio/snapshot")

        assert resp.status_code == 200
        data = resp.json()
        assert data["total_return_pct"] == pytest.approx(5.0)
        assert data["open_position_count"] == 2

    @pytest.mark.asyncio
    async def test_snapshot_refresh_false_passes_flag(self, client):
        snap = self._make_snapshot()
        with patch("app.api.v1.endpoints.portfolio.build_snapshot", new_callable=AsyncMock) as m:
            m.return_value = snap
            resp = await client.get("/api/v1/portfolio/snapshot?refresh=false")

        assert resp.status_code == 200
        m.assert_called_once_with(refresh_mtm=False)

    @pytest.mark.asyncio
    async def test_snapshot_refresh_true_by_default(self, client):
        snap = self._make_snapshot()
        with patch("app.api.v1.endpoints.portfolio.build_snapshot", new_callable=AsyncMock) as m:
            m.return_value = snap
            resp = await client.get("/api/v1/portfolio/snapshot")

        m.assert_called_once_with(refresh_mtm=True)


# ─────────────────────────────────────────────────────────────────────────────
# Positions
# ─────────────────────────────────────────────────────────────────────────────

class TestPositionEndpoints:
    def _make_position(self, symbol: str = "RELIANCE") -> Position:
        pos = Position(
            symbol=symbol,
            net_quantity=100,
            avg_cost_inr=Decimal("1000"),
            realized_pnl_inr=Decimal("5000"),
        )
        pos.recompute_from_mtm(Decimal("1100"))
        return pos

    @pytest.mark.asyncio
    async def test_list_positions_empty(self, client):
        with patch("app.api.v1.endpoints.portfolio.repo") as mock_repo:
            mock_repo.list_positions = AsyncMock(return_value=[])
            resp = await client.get("/api/v1/portfolio/positions")

        assert resp.status_code == 200
        assert resp.json() == {"positions": [], "count": 0}

    @pytest.mark.asyncio
    async def test_list_positions_with_data(self, client):
        positions = [self._make_position("RELIANCE"), self._make_position("INFY")]
        with patch("app.api.v1.endpoints.portfolio.repo") as mock_repo:
            mock_repo.list_positions = AsyncMock(return_value=positions)
            resp = await client.get("/api/v1/portfolio/positions")

        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 2
        symbols = [p["symbol"] for p in data["positions"]]
        assert "RELIANCE" in symbols
        assert "INFY" in symbols

    @pytest.mark.asyncio
    async def test_get_position_found(self, client):
        pos = self._make_position("TCS")
        with patch("app.api.v1.endpoints.portfolio.repo") as mock_repo:
            mock_repo.get_position = AsyncMock(return_value=pos)
            resp = await client.get("/api/v1/portfolio/positions/TCS")

        assert resp.status_code == 200
        data = resp.json()
        assert data["symbol"] == "TCS"
        assert data["net_quantity"] == 100

    @pytest.mark.asyncio
    async def test_get_position_not_found(self, client):
        with patch("app.api.v1.endpoints.portfolio.repo") as mock_repo:
            mock_repo.get_position = AsyncMock(return_value=None)
            resp = await client.get("/api/v1/portfolio/positions/UNKNOWN")

        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_get_position_symbol_uppercased(self, client):
        pos = self._make_position("RELIANCE")
        with patch("app.api.v1.endpoints.portfolio.repo") as mock_repo:
            mock_repo.get_position = AsyncMock(return_value=pos)
            resp = await client.get("/api/v1/portfolio/positions/reliance")

        mock_repo.get_position.assert_called_once_with("RELIANCE")

    @pytest.mark.asyncio
    async def test_list_positions_include_flat_param(self, client):
        with patch("app.api.v1.endpoints.portfolio.repo") as mock_repo:
            mock_repo.list_positions = AsyncMock(return_value=[])
            await client.get("/api/v1/portfolio/positions?include_flat=true")

        mock_repo.list_positions.assert_called_once_with(include_flat=True)


# ─────────────────────────────────────────────────────────────────────────────
# Exposure
# ─────────────────────────────────────────────────────────────────────────────

class TestExposureEndpoint:
    @pytest.mark.asyncio
    async def test_exposure_empty_portfolio(self, client):
        with (
            patch("app.api.v1.endpoints.portfolio.repo") as mock_repo,
            patch("app.api.v1.endpoints.portfolio.get_portfolio_totals", new_callable=AsyncMock) as mock_totals,
        ):
            mock_repo.list_positions = AsyncMock(return_value=[])
            mock_totals.return_value = {
                "gross_exposure_inr": Decimal("0"),
                "net_exposure_inr": Decimal("0"),
                "gross_exposure_pct": 0.0,
                "total_value_inr": Decimal("1000000"),
                "open_position_count": 0,
            }
            resp = await client.get("/api/v1/portfolio/exposure")

        assert resp.status_code == 200
        data = resp.json()
        assert data["open_position_count"] == 0
        assert data["by_symbol"] == []

    @pytest.mark.asyncio
    async def test_exposure_sorted_by_market_value_desc(self, client):
        big = Position(symbol="RELIANCE", net_quantity=1000, avg_cost_inr=Decimal("1000"))
        big.recompute_from_mtm(Decimal("1100"))
        small = Position(symbol="INFY", net_quantity=10, avg_cost_inr=Decimal("1500"))
        small.recompute_from_mtm(Decimal("1500"))

        with (
            patch("app.api.v1.endpoints.portfolio.repo") as mock_repo,
            patch("app.api.v1.endpoints.portfolio.get_portfolio_totals", new_callable=AsyncMock) as mock_totals,
        ):
            mock_repo.list_positions = AsyncMock(return_value=[small, big])
            mock_totals.return_value = {
                "gross_exposure_inr": Decimal("1115000"),
                "net_exposure_inr": Decimal("1115000"),
                "gross_exposure_pct": 100.0,
                "total_value_inr": Decimal("1115000"),
                "open_position_count": 2,
            }
            resp = await client.get("/api/v1/portfolio/exposure")

        data = resp.json()
        symbols = [s["symbol"] for s in data["by_symbol"]]
        # RELIANCE (1,100,000) should come before INFY (15,000)
        assert symbols[0] == "RELIANCE"
        assert symbols[1] == "INFY"


# ─────────────────────────────────────────────────────────────────────────────
# Performance
# ─────────────────────────────────────────────────────────────────────────────

class TestPerformanceEndpoints:
    def _make_metrics(self, window: PerformanceWindow) -> PerformanceMetrics:
        return PerformanceMetrics(
            window=window,
            total_return_pct=12.5,
            sharpe_ratio=1.8,
            max_drawdown_pct=5.2,
            win_rate_pct=62.0,
        )

    @pytest.mark.asyncio
    async def test_performance_30d(self, client):
        metrics = self._make_metrics(PerformanceWindow.DAYS_30)
        with patch("app.api.v1.endpoints.performance.compute_performance", new_callable=AsyncMock) as m:
            m.return_value = metrics
            resp = await client.get("/api/v1/performance/30d")

        assert resp.status_code == 200
        data = resp.json()
        assert data["total_return_pct"] == pytest.approx(12.5)
        assert data["sharpe_ratio"] == pytest.approx(1.8)

    @pytest.mark.asyncio
    async def test_performance_invalid_window(self, client):
        resp = await client.get("/api/v1/performance/invalid_window")
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_performance_all_valid_windows(self, client):
        for window in ("1d", "7d", "30d", "90d", "252d", "inception"):
            with patch(
                "app.api.v1.endpoints.performance.compute_performance", new_callable=AsyncMock
            ) as m:
                m.return_value = self._make_metrics(PerformanceWindow.DAYS_30)
                resp = await client.get(f"/api/v1/performance/{window}")
            assert resp.status_code == 200, f"Failed for window={window}"

    @pytest.mark.asyncio
    async def test_performance_summary_returns_three_windows(self, client):
        with patch(
            "app.api.v1.endpoints.performance.compute_performance", new_callable=AsyncMock
        ) as m:
            m.return_value = self._make_metrics(PerformanceWindow.DAYS_30)
            resp = await client.get("/api/v1/performance/summary")

        assert resp.status_code == 200
        data = resp.json()
        assert "1d" in data
        assert "30d" in data
        assert "252d" in data


# ─────────────────────────────────────────────────────────────────────────────
# Ledger
# ─────────────────────────────────────────────────────────────────────────────

class TestLedgerEndpoints:
    @pytest.mark.asyncio
    async def test_list_trades_empty(self, client):
        with patch("app.api.v1.endpoints.ledger.repo") as mock_repo:
            mock_repo.list_trade_ledger = AsyncMock(return_value=[])
            resp = await client.get("/api/v1/ledger/trades")

        assert resp.status_code == 200
        assert resp.json() == {"trades": [], "count": 0}

    @pytest.mark.asyncio
    async def test_list_trades_with_symbol_filter(self, client):
        trade = {
            "event_id": str(uuid.uuid4()),
            "symbol": "RELIANCE",
            "action": "BUY",
            "filled_quantity": 100,
            "avg_fill_price_inr": "1000.00",
        }
        with patch("app.api.v1.endpoints.ledger.repo") as mock_repo:
            mock_repo.list_trade_ledger = AsyncMock(return_value=[trade])
            resp = await client.get("/api/v1/ledger/trades?symbol=RELIANCE")

        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 1
        mock_repo.list_trade_ledger.assert_called_once()
        call_kwargs = mock_repo.list_trade_ledger.call_args.kwargs
        assert call_kwargs["symbol"] == "RELIANCE"

    @pytest.mark.asyncio
    async def test_list_snapshots_empty(self, client):
        with patch("app.api.v1.endpoints.ledger.repo") as mock_repo:
            mock_repo.list_snapshots = AsyncMock(return_value=[])
            resp = await client.get("/api/v1/ledger/snapshots")

        assert resp.status_code == 200
        assert resp.json()["count"] == 0

    @pytest.mark.asyncio
    async def test_get_latest_snapshot_not_found(self, client):
        with patch("app.api.v1.endpoints.ledger.repo") as mock_repo:
            mock_repo.get_latest_snapshot = AsyncMock(return_value=None)
            resp = await client.get("/api/v1/ledger/snapshots/latest")

        assert resp.status_code == 200
        assert resp.json() == {}

    @pytest.mark.asyncio
    async def test_get_latest_snapshot_with_data(self, client):
        snap_row = {
            "snapshot_id": str(uuid.uuid4()),
            "total_value_inr": "1050000",
            "total_return_pct": "5.0",
        }
        with patch("app.api.v1.endpoints.ledger.repo") as mock_repo:
            mock_repo.get_latest_snapshot = AsyncMock(return_value=snap_row)
            resp = await client.get("/api/v1/ledger/snapshots/latest")

        assert resp.status_code == 200
        assert "total_value_inr" in resp.json()

    @pytest.mark.asyncio
    async def test_trades_limit_and_offset(self, client):
        with patch("app.api.v1.endpoints.ledger.repo") as mock_repo:
            mock_repo.list_trade_ledger = AsyncMock(return_value=[])
            await client.get("/api/v1/ledger/trades?limit=50&offset=100")

        call_kwargs = mock_repo.list_trade_ledger.call_args.kwargs
        assert call_kwargs["limit"] == 50
        assert call_kwargs["offset"] == 100
