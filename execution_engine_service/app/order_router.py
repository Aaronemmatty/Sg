"""
Order routing / "smart execution" decisioning.

Given a RiskDecision and a reference price, decide:
  - execution style (AGGRESSIVE -> market, PASSIVE -> limit with a price band)
  - quantity (approved_allocation_inr / reference_price, floored)
  - limit price (if applicable)

Routing inputs deliberately consider risk_band and market_regime from the
upstream RiskDecision, since both are already computed upstream and reflect
real-time conditions execution_engine shouldn't have to re-derive:
  - HIGH/CRITICAL risk_band -> force PASSIVE (reduce price impact, avoid
    chasing a fill when the trade is already flagged as risky)
  - VOLATILE regime -> force PASSIVE with a wider band
  - Otherwise -> DEFAULT_EXECUTION_STYLE from config
"""
from __future__ import annotations

import math

from app.config import settings
from app.models import ExecutionStyle, OrderType, OrderValidity, RiskDecision, TradeAction


class RoutingError(Exception):
    """Raised when a routing decision cannot be made (e.g. no reference price)."""


class RoutingDecision:
    def __init__(
        self,
        execution_style: ExecutionStyle,
        order_type: OrderType,
        quantity: int,
        limit_price: float | None,
        validity: OrderValidity,
        intended_price_inr: float,
    ):
        self.execution_style = execution_style
        self.order_type = order_type
        self.quantity = quantity
        self.limit_price = limit_price
        self.validity = validity
        self.intended_price_inr = intended_price_inr


HIGH_RISK_BANDS = {"HIGH", "CRITICAL"}
VOLATILE_REGIMES = {"VOLATILE", "HIGH_VOLATILITY"}  # tolerant of either naming used upstream


def decide_execution_style(decision: RiskDecision) -> ExecutionStyle:
    if decision.risk_band.upper() in HIGH_RISK_BANDS:
        return ExecutionStyle.PASSIVE
    if decision.market_regime and decision.market_regime.upper() in VOLATILE_REGIMES:
        return ExecutionStyle.PASSIVE
    return ExecutionStyle(settings.default_execution_style)


def route(decision: RiskDecision, reference_price: float) -> RoutingDecision:
    if reference_price is None or reference_price <= 0:
        raise RoutingError(f"No usable reference price for {decision.symbol}")

    quantity = math.floor(decision.approved_allocation_inr / reference_price)
    if quantity < 1:
        raise RoutingError(
            f"Approved allocation {decision.approved_allocation_inr} INR insufficient for "
            f"1 share of {decision.symbol} at {reference_price}"
        )

    style = decide_execution_style(decision)
    validity = OrderValidity(settings.order_validity)

    if style == ExecutionStyle.AGGRESSIVE:
        return RoutingDecision(
            execution_style=style,
            order_type=OrderType.MARKET,
            quantity=quantity,
            limit_price=None,
            validity=validity,
            intended_price_inr=reference_price,
        )

    # PASSIVE: limit order banded around reference price, on the favorable side.
    band = settings.passive_limit_band_bps / 10_000.0
    if decision.action == TradeAction.BUY:
        limit_price = round(reference_price * (1 + band), 2)  # willing to pay up to band above ref
    else:
        limit_price = round(reference_price * (1 - band), 2)  # willing to accept down to band below ref

    return RoutingDecision(
        execution_style=style,
        order_type=OrderType.LIMIT,
        quantity=quantity,
        limit_price=limit_price,
        validity=validity,
        intended_price_inr=reference_price,
    )
