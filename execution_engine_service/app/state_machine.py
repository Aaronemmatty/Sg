"""
Order lifecycle state machine.

Every state transition for an Order MUST go through `transition()` so that
illegal jumps (e.g. PENDING -> FILLED) are impossible and every change is
auditable. This mirrors the "no silent state mutation" discipline used by
risk_engine_service's decision/audit pipeline.
"""
from __future__ import annotations

from app.models import OrderState, TERMINAL_STATES


class InvalidTransitionError(Exception):
    def __init__(self, current: OrderState, target: OrderState):
        self.current = current
        self.target = target
        super().__init__(f"Illegal order state transition: {current} -> {target}")


# Adjacency list of legal transitions.
ALLOWED_TRANSITIONS: dict[OrderState, set[OrderState]] = {
    OrderState.PENDING: {OrderState.ROUTING, OrderState.HELD, OrderState.FAILED},
    OrderState.HELD: {OrderState.ROUTING, OrderState.EXPIRED, OrderState.CANCELLED},
    OrderState.ROUTING: {OrderState.SUBMITTED, OrderState.FAILED},
    OrderState.SUBMITTED: {
        OrderState.ACKNOWLEDGED,
        OrderState.PARTIALLY_FILLED,  # fast fill observed before any ACKNOWLEDGED status was seen
        OrderState.FILLED,            # market orders can fill before the first status poll
        OrderState.REJECTED,
        OrderState.FAILED,
        OrderState.CANCELLED,
        OrderState.EXPIRED,
    },
    OrderState.ACKNOWLEDGED: {
        OrderState.PARTIALLY_FILLED,
        OrderState.FILLED,
        OrderState.CANCELLED,
        OrderState.REJECTED,
        OrderState.EXPIRED,
        OrderState.FAILED,
    },
    OrderState.PARTIALLY_FILLED: {
        OrderState.PARTIALLY_FILLED,  # additional partial fills
        OrderState.FILLED,
        OrderState.CANCELLED,
        OrderState.EXPIRED,
        OrderState.FAILED,
    },
    # Terminal states: no outbound transitions.
    OrderState.FILLED: set(),
    OrderState.REJECTED: set(),
    OrderState.CANCELLED: set(),
    OrderState.EXPIRED: set(),
    OrderState.FAILED: set(),
}


def is_terminal(state: OrderState) -> bool:
    return state in TERMINAL_STATES


def can_transition(current: OrderState, target: OrderState) -> bool:
    return target in ALLOWED_TRANSITIONS.get(current, set())


def transition(current: OrderState, target: OrderState) -> OrderState:
    """Validate and return the target state, or raise InvalidTransitionError."""
    if not can_transition(current, target):
        raise InvalidTransitionError(current, target)
    return target
