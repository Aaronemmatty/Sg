"""Unit tests — capital allocator."""
from __future__ import annotations

import pytest
from datetime import datetime, timezone

from app.models.domain import MarketRegime, PortfolioState
from app.orchestrator.allocator import compute_allocation


def _portfolio(total=1_000_000.0, cash=500_000.0) -> PortfolioState:
    return PortfolioState(
        portfolio_id="test",
        total_value_inr=total,
        cash_inr=cash,
        equity_inr=total - cash,
        day_pnl_inr=0.0,
        total_pnl_inr=0.0,
        positions=[],
        as_of=datetime.now(timezone.utc),
    )


def test_zero_portfolio_returns_zero_allocation():
    result = compute_allocation(0.85, _portfolio(total=0.0), "TRENDING")
    assert result.allocation_inr == 0.0
    assert result.risk_percent == 0.0


def test_high_confidence_trending_produces_positive_allocation():
    result = compute_allocation(0.80, _portfolio(), MarketRegime.TRENDING.value)
    assert result.allocation_inr > 0


def test_volatile_regime_lower_than_trending():
    trending = compute_allocation(0.80, _portfolio(), MarketRegime.TRENDING.value)
    volatile = compute_allocation(0.80, _portfolio(), MarketRegime.VOLATILE.value)
    assert volatile.allocation_inr < trending.allocation_inr


def test_sideways_regime_lowest():
    trending = compute_allocation(0.80, _portfolio(), MarketRegime.TRENDING.value)
    sideways = compute_allocation(0.80, _portfolio(), MarketRegime.SIDEWAYS.value)
    assert sideways.allocation_inr < trending.allocation_inr


def test_allocation_never_exceeds_max_cap():
    """Even with max confidence and huge portfolio, cap applies."""
    result = compute_allocation(1.0, _portfolio(total=100_000_000.0), "TRENDING")
    from app.core.config import get_settings
    assert result.allocation_inr <= get_settings().MAX_ALLOCATION_INR


def test_low_confidence_below_50_returns_zero():
    """Kelly edge goes negative when confidence < 0.5 — allocation should be 0."""
    result = compute_allocation(0.40, _portfolio(), "TRENDING")
    assert result.allocation_inr == 0.0


def test_allocation_scales_with_portfolio_size():
    small = compute_allocation(0.75, _portfolio(total=100_000.0), "TRENDING")
    large = compute_allocation(0.75, _portfolio(total=1_000_000.0), "TRENDING")
    assert large.allocation_inr > small.allocation_inr


def test_unknown_regime_treated_conservatively():
    trending = compute_allocation(0.80, _portfolio(), MarketRegime.TRENDING.value)
    unknown = compute_allocation(0.80, _portfolio(), MarketRegime.UNKNOWN.value)
    assert unknown.allocation_inr < trending.allocation_inr


def test_basis_string_is_populated():
    result = compute_allocation(0.75, _portfolio(), "TRENDING")
    assert result.basis != ""
    assert "kelly_frac" in result.basis
