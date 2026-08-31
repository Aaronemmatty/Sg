"""
Slippage tracking.

slippage_inr  = signed INR difference between intended and actual fill price,
                from the trader's perspective (positive = worse than intended).
slippage_bps  = same, in basis points of intended price.
"""
from __future__ import annotations

from app.models import TradeAction


def compute_slippage(
    intended_price_inr: float, fill_price_inr: float, action: TradeAction
) -> tuple[float, float]:
    if intended_price_inr <= 0:
        return 0.0, 0.0

    if action == TradeAction.BUY:
        # Paying more than intended is bad (positive slippage).
        diff = fill_price_inr - intended_price_inr
    else:
        # Receiving less than intended is bad (positive slippage).
        diff = intended_price_inr - fill_price_inr

    slippage_bps = (diff / intended_price_inr) * 10_000.0
    return round(diff, 4), round(slippage_bps, 4)


def weighted_avg_price(fills: list[tuple[int, float]]) -> float:
    """fills: list of (quantity, price). Returns quantity-weighted average price."""
    total_qty = sum(q for q, _ in fills)
    if total_qty == 0:
        return 0.0
    return sum(q * p for q, p in fills) / total_qty
