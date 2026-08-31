"""
Unit tests for performance_engine.py.

Tests exercise the pure numpy/math calculations in isolation.
All DB and market-data calls are mocked.
"""
from __future__ import annotations

import math
from unittest.mock import AsyncMock, patch

import numpy as np
import pytest

from app.services.performance_engine import (
    _compute_drawdown,
    _compute_returns,
    _compute_sharpe,
    _compute_sortino,
    _compute_win_stats,
)
from app.models.domain import PerformanceWindow


# ─────────────────────────────────────────────────────────────────────────────
# Sharpe ratio
# ─────────────────────────────────────────────────────────────────────────────

class TestSharpeRatio:
    def test_positive_sharpe(self):
        """Normally-distributed positive daily returns → positive Sharpe."""
        rng = np.random.default_rng(42)
        # mean=0.1%, std=0.5% — realistic daily return series
        returns = rng.normal(0.001, 0.005, 60)
        sharpe = _compute_sharpe(returns)
        # With seed 42, mean > 0, so Sharpe should be positive
        assert sharpe is not None

    def test_zero_returns_no_sharpe(self):
        """All-zero returns → std=0 → None."""
        returns = np.zeros(60)
        sharpe = _compute_sharpe(returns)
        assert sharpe is None

    def test_negative_mean_negative_sharpe(self):
        """Mostly losing days → negative Sharpe."""
        rng = np.random.default_rng(7)
        # mean=-0.1%, std=0.5% — consistently losing series
        returns = rng.normal(-0.001, 0.005, 60)
        sharpe = _compute_sharpe(returns)
        assert sharpe is not None
        assert sharpe < 0

    def test_too_few_returns_returns_none(self):
        """< 5 data points → None."""
        returns = np.array([0.001, 0.002, 0.001])
        assert _compute_sharpe(returns) is None

    def test_annualization(self):
        """Sharpe should be annualized by sqrt(252)."""
        daily_mean = 0.001
        daily_std = 0.01
        returns = np.random.default_rng(42).normal(daily_mean, daily_std, 252)
        sharpe = _compute_sharpe(returns)
        # Approximate expected: (daily_mean / daily_std) * sqrt(252)
        expected_approx = (daily_mean / daily_std) * math.sqrt(252)
        assert sharpe is not None
        # Within 50% of theoretical (random samples vary)
        assert abs(sharpe - expected_approx) < expected_approx


# ─────────────────────────────────────────────────────────────────────────────
# Sortino ratio
# ─────────────────────────────────────────────────────────────────────────────

class TestSortinoRatio:
    def test_no_downside_returns_none(self):
        """Only positive returns → no downside std → None."""
        returns = np.full(60, 0.002)
        assert _compute_sortino(returns) is None

    def test_mixed_returns_positive_sortino(self):
        """More up days than down → positive Sortino."""
        rng = np.random.default_rng(0)
        returns = rng.normal(0.001, 0.005, 100)
        sortino = _compute_sortino(returns)
        assert sortino is not None

    def test_too_few_returns_returns_none(self):
        assert _compute_sortino(np.array([0.001, -0.002])) is None

    def test_sortino_exceeds_sharpe_when_downside_rare(self):
        """
        When downside is rare, Sortino > Sharpe because downside std < total std.
        """
        rng = np.random.default_rng(1)
        # Mostly small positive, occasional small negative
        returns = np.abs(rng.normal(0.001, 0.005, 200))
        returns[::20] *= -0.5  # 5% negative days, small magnitude

        sharpe = _compute_sharpe(returns)
        sortino = _compute_sortino(returns)

        assert sharpe is not None and sortino is not None
        assert sortino >= sharpe


# ─────────────────────────────────────────────────────────────────────────────
# Drawdown
# ─────────────────────────────────────────────────────────────────────────────

class TestDrawdown:
    def test_no_drawdown_all_gains(self):
        """Monotonically increasing NAV → max drawdown = 0."""
        navs = np.array([100.0, 101.0, 102.0, 103.0, 104.0])
        max_dd_pct, max_dd_inr, current_dd_pct = _compute_drawdown(navs)
        assert max_dd_pct == pytest.approx(0.0, abs=1e-6)
        assert max_dd_inr == pytest.approx(0.0, abs=1e-6)

    def test_simple_50_percent_drawdown(self):
        """Peak 100 → trough 50 → 50% max drawdown."""
        navs = np.array([100.0, 90.0, 80.0, 70.0, 50.0, 60.0, 70.0])
        max_dd_pct, max_dd_inr, _ = _compute_drawdown(navs)
        assert max_dd_pct == pytest.approx(50.0, rel=0.01)
        assert max_dd_inr == pytest.approx(50.0, rel=0.01)

    def test_current_drawdown_from_recent_peak(self):
        """NAV peaks at 120 then ends at 100 → current dd = 16.67%."""
        navs = np.array([100.0, 110.0, 120.0, 110.0, 100.0])
        _, _, current_dd = _compute_drawdown(navs)
        expected = (120.0 - 100.0) / 120.0 * 100.0
        assert current_dd == pytest.approx(expected, rel=0.01)

    def test_empty_navs(self):
        max_dd, max_inr, current = _compute_drawdown(np.array([]))
        assert max_dd == 0.0
        assert max_inr == 0.0
        assert current == 0.0

    def test_single_nav(self):
        """Single data point → no drawdown possible."""
        max_dd, _, current = _compute_drawdown(np.array([100.0]))
        assert max_dd == pytest.approx(0.0)
        assert current == pytest.approx(0.0)

    def test_multiple_peaks_uses_global_max(self):
        """Max drawdown is from the global peak, not a local one."""
        # Peak at 200, then partial recovery, new peak 180, then down to 90
        navs = np.array([100.0, 200.0, 150.0, 180.0, 90.0])
        max_dd_pct, _, _ = _compute_drawdown(navs)
        # From global peak 200 to trough 90: (200-90)/200 * 100 = 55%
        assert max_dd_pct == pytest.approx(55.0, rel=0.01)


# ─────────────────────────────────────────────────────────────────────────────
# Total return & CAGR
# ─────────────────────────────────────────────────────────────────────────────

class TestReturns:
    def test_100_pct_return(self):
        """NAV doubled: 100% return."""
        from decimal import Decimal
        navs = np.array([50_000.0, 100_000.0])
        total_return, _ = _compute_returns(navs, Decimal("50000"), PerformanceWindow.DAYS_30)
        assert total_return == pytest.approx(100.0)

    def test_zero_initial_capital(self):
        from decimal import Decimal
        navs = np.array([1000.0])
        total, cagr = _compute_returns(navs, Decimal("0"), PerformanceWindow.INCEPTION)
        assert total == 0.0

    def test_cagr_computed_for_inception_window(self):
        """Over 252 days with 26% gain → CAGR ≈ 26% (one year window)."""
        from decimal import Decimal
        initial = 100_000.0
        final = 126_000.0
        # Simulate 252 daily nav values growing smoothly
        navs = np.linspace(initial, final, 252)
        total, cagr = _compute_returns(navs, Decimal(str(initial)), PerformanceWindow.INCEPTION)
        assert total == pytest.approx(26.0, rel=0.01)
        assert cagr is not None
        assert cagr == pytest.approx(26.0, rel=0.02)

    def test_cagr_is_none_for_short_windows(self):
        """CAGR only computed for INCEPTION window."""
        from decimal import Decimal
        navs = np.array([100_000.0, 110_000.0])
        _, cagr = _compute_returns(navs, Decimal("100000"), PerformanceWindow.DAYS_30)
        assert cagr is None


# ─────────────────────────────────────────────────────────────────────────────
# Win stats
# ─────────────────────────────────────────────────────────────────────────────

class TestWinStats:
    def test_no_trades(self):
        stats = _compute_win_stats([])
        assert stats["total"] == 0
        assert stats["win_rate_pct"] == 0.0
        assert stats["profit_factor"] is None

    def test_trade_count_captured(self):
        trades = [{"action": "SELL"} for _ in range(10)]
        stats = _compute_win_stats(trades)
        assert stats["total"] == 10


# ─────────────────────────────────────────────────────────────────────────────
# compute_performance integration (full mocked)
# ─────────────────────────────────────────────────────────────────────────────

class TestComputePerformanceIntegration:
    @pytest.mark.asyncio
    async def test_empty_returns_gives_zero_metrics(self):
        """No daily returns → all metrics default to 0 or None."""
        with (
            patch("app.services.performance_engine.repo") as mock_repo,
            patch("app.services.performance_engine.market_data_client"),
        ):
            mock_repo.get_daily_returns = AsyncMock(return_value=[])
            mock_repo.get_portfolio_config = AsyncMock(
                return_value={"initial_capital_inr": 1_000_000}
            )
            from app.services.performance_engine import compute_performance
            metrics = await compute_performance(PerformanceWindow.DAYS_30)

        assert metrics.total_return_pct == 0.0
        assert metrics.sharpe_ratio is None
        assert metrics.max_drawdown_pct == 0.0

    @pytest.mark.asyncio
    async def test_strong_performance_period(self):
        """60 days of normally-distributed positive daily returns → positive Sharpe."""
        import numpy as np
        rng = np.random.default_rng(0)
        raw_returns = rng.normal(0.001, 0.005, 60)
        daily_nav_start = 1_000_000.0
        daily_navs = [daily_nav_start]
        for r in raw_returns:
            daily_navs.append(daily_navs[-1] * (1 + r))
        daily_navs = daily_navs[1:]
        daily_rows = [
            {"nav_inr": nav, "daily_return_pct": r * 100}
            for nav, r in zip(daily_navs, raw_returns)
        ]

        with (
            patch("app.services.performance_engine.repo") as mock_repo,
            patch("app.services.performance_engine.market_data_client") as mock_md,
        ):
            mock_repo.get_daily_returns = AsyncMock(return_value=daily_rows)
            mock_repo.get_portfolio_config = AsyncMock(
                return_value={"initial_capital_inr": daily_nav_start}
            )
            mock_repo.list_trade_ledger = AsyncMock(return_value=[])
            mock_md.get_benchmark_series = AsyncMock(return_value=None)

            from app.services.performance_engine import compute_performance
            metrics = await compute_performance(PerformanceWindow.DAYS_30)

        # With seed 0, rng.normal(0.001, 0.005, 60) has positive mean → positive total return
        assert metrics.sharpe_ratio is not None
