"""
Capital Allocator — position sizing and allocation recommendation.

Uses a fractional Kelly approach scaled by:
  - signal confidence
  - portfolio size
  - regime multipliers (reduce size in volatile / sideways regimes)
  - configured risk % cap

Allocation limits are expressed as percentages of the CURRENT live portfolio
value (fetched from broker_service each cycle), so they automatically
recalibrate as the account grows or shrinks with P&L.
"""
from __future__ import annotations

from app.core.config import get_settings
from app.core.logging import get_logger
from app.models.domain import AllocationResult, MarketRegime, PortfolioState

settings = get_settings()
log = get_logger(__name__)

# Regime multipliers — scale allocation down in unfavourable regimes
_REGIME_MULTIPLIER: dict[str, float] = {
    MarketRegime.TRENDING.value: 1.0,
    MarketRegime.MEAN_REVERTING.value: 0.75,
    MarketRegime.VOLATILE.value: 0.50,
    MarketRegime.SIDEWAYS.value: 0.40,
    MarketRegime.UNKNOWN.value: 0.60,
}

# Kelly fraction — use a quarter-Kelly to be conservative
KELLY_FRACTION = 0.25


def _regime_multiplier(regime: str) -> float:
    return _REGIME_MULTIPLIER.get(regime, 0.60)


def compute_allocation(
    confidence: float,
    portfolio: PortfolioState,
    market_regime: str,
    risk_pct: float = None,
) -> AllocationResult:
    """
    Compute recommended capital allocation for one trade intent.

    Limits are percentage-based and applied to the CURRENT live portfolio
    value (portfolio.total_value_inr) so they recalibrate automatically as
    the account balance changes with P&L:

        max_allocation = portfolio_value * MAX_ALLOCATION_PCT  (20%)
        min_allocation = portfolio_value * MIN_ALLOCATION_PCT  ( 4%)

    Formula:
        kelly_edge  = confidence - (1 - confidence)          # win - loss
        kelly_frac  = kelly_edge / 1.0                       # odds = 1:1
        adjusted_f  = KELLY_FRACTION * kelly_frac * regime_mul
        allocation  = portfolio_value * adjusted_f

    Capped at max_allocation, floored at 0 (min floor enforced in pipeline).
    """
    portfolio_value = portfolio.total_value_inr

    if portfolio_value <= 0:
        return AllocationResult(
            allocation_inr=0.0,
            risk_percent=0.0,
            basis="portfolio_value_zero",
        )

    # Dynamic caps — 20% / 4% of the CURRENT live portfolio value
    max_allocation_inr = portfolio_value * settings.MAX_ALLOCATION_PCT
    min_allocation_inr = portfolio_value * settings.MIN_ALLOCATION_PCT

    # Fractional Kelly
    kelly_edge = confidence - (1.0 - confidence)
    kelly_frac = max(kelly_edge, 0.0)  # never go negative
    regime_mul = _regime_multiplier(market_regime)
    adjusted_f = KELLY_FRACTION * kelly_frac * regime_mul
    kelly_based = portfolio_value * adjusted_f

    # Scale by configured risk % if explicitly provided; otherwise Kelly + max cap
    if risk_pct is not None:
        risk_based = portfolio_value * (risk_pct / 100.0)
        allocation = min(kelly_based, risk_based)
    else:
        allocation = kelly_based

    # Hard cap: 20% of live balance
    allocation = min(allocation, max_allocation_inr)
    allocation = max(allocation, 0.0)


    actual_risk_pct = (allocation / portfolio_value * 100.0) if portfolio_value > 0 else 0.0

    basis = (
        f"kelly_frac={kelly_frac:.3f} "
        f"regime_mul={regime_mul:.2f} "
        f"kelly_based={kelly_based:.0f} "
        f"max_cap={max_allocation_inr:.0f} "
        f"min_floor={min_allocation_inr:.0f} "
        f"final={allocation:.0f}"
    )


    log.debug(
        "allocation_computed",
        confidence=confidence,
        market_regime=market_regime,
        kelly_frac=round(kelly_frac, 4),
        regime_mul=regime_mul,
        portfolio_value=portfolio_value,
        max_allocation_inr=round(max_allocation_inr, 2),
        min_allocation_inr=round(min_allocation_inr, 2),
        allocation=round(allocation, 2),
        risk_pct=round(actual_risk_pct, 4),
    )

    return AllocationResult(
        allocation_inr=round(allocation, 2),
        risk_percent=round(actual_risk_pct, 4),
        basis=basis,
        min_allocation_inr=round(min_allocation_inr, 2),
    )
