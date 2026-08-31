"""
Capital Allocator — position sizing and allocation recommendation.

Uses a fractional Kelly approach scaled by:
  - signal confidence
  - portfolio size
  - regime multipliers (reduce size in volatile / sideways regimes)
  - configured risk % cap
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

    Formula:
        kelly_edge  = confidence - (1 - confidence)          # win - loss
        kelly_frac  = kelly_edge / 1.0                       # odds = 1:1
        adjusted_f  = KELLY_FRACTION * kelly_frac * regime_mul
        allocation  = portfolio_value * adjusted_f

    Capped at MAX_ALLOCATION_INR, floored at MIN_ALLOCATION_INR.
    """
    risk_pct = risk_pct or settings.DEFAULT_RISK_PCT
    portfolio_value = portfolio.total_value_inr

    if portfolio_value <= 0:
        return AllocationResult(
            allocation_inr=0.0,
            risk_percent=0.0,
            basis="portfolio_value_zero",
        )

    # Fractional Kelly
    kelly_edge = confidence - (1.0 - confidence)
    kelly_frac = max(kelly_edge, 0.0)  # never go negative
    regime_mul = _regime_multiplier(market_regime)
    adjusted_f = KELLY_FRACTION * kelly_frac * regime_mul

    # Scale by configured risk % as a secondary cap
    risk_based = portfolio_value * (risk_pct / 100.0)
    kelly_based = portfolio_value * adjusted_f

    allocation = min(kelly_based, risk_based)

    # Hard caps
    allocation = min(allocation, settings.MAX_ALLOCATION_INR)
    allocation = max(allocation, 0.0)

    actual_risk_pct = (allocation / portfolio_value * 100.0) if portfolio_value > 0 else 0.0

    basis = (
        f"kelly_frac={kelly_frac:.3f} "
        f"regime_mul={regime_mul:.2f} "
        f"kelly_based={kelly_based:.0f} "
        f"risk_cap={risk_based:.0f} "
        f"final={allocation:.0f}"
    )

    log.debug(
        "allocation_computed",
        confidence=confidence,
        market_regime=market_regime,
        kelly_frac=round(kelly_frac, 4),
        regime_mul=regime_mul,
        portfolio_value=portfolio_value,
        allocation=round(allocation, 2),
        risk_pct=round(actual_risk_pct, 4),
    )

    return AllocationResult(
        allocation_inr=round(allocation, 2),
        risk_percent=round(actual_risk_pct, 4),
        basis=basis,
    )
