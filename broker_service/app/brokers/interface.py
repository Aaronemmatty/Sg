"""
BrokerInterface — the contract every concrete broker must implement.

All methods are async. Sync broker SDKs (like kiteconnect) must
wrap calls in run_in_executor inside their implementation.

Design principles:
  - Zero broker-specific logic leaks outside the adapter
  - Callers never import kiteconnect / any broker SDK directly
  - All exceptions raised as BrokerError subtypes
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional

from app.core.types import (
    AccountInfo,
    OrderBookEntry,
    OrderRequest,
    OrderResult,
    Position,
)


class BrokerError(Exception):
    """Base broker error."""
    def __init__(self, message: str, code: str = "broker_error", retryable: bool = False):
        self.message = message
        self.code = code
        self.retryable = retryable
        super().__init__(message)


class OrderRejectedError(BrokerError):
    """Order rejected by broker / exchange — do NOT retry."""
    def __init__(self, message: str, reason: str = ""):
        self.reason = reason
        super().__init__(message, code="order_rejected", retryable=False)


class InsufficientFundsError(BrokerError):
    def __init__(self, message: str):
        super().__init__(message, code="insufficient_funds", retryable=False)


class RateLimitError(BrokerError):
    def __init__(self, message: str):
        super().__init__(message, code="rate_limit", retryable=True)


class NetworkError(BrokerError):
    def __init__(self, message: str):
        super().__init__(message, code="network_error", retryable=True)


class AuthenticationError(BrokerError):
    def __init__(self, message: str):
        super().__init__(message, code="auth_error", retryable=False)


class BrokerInterface(ABC):
    """Abstract broker — all concrete adapters implement this."""

    @property
    @abstractmethod
    def broker_name(self) -> str:
        """Human-readable broker identifier e.g. 'kite', 'paper'."""
        ...

    @property
    @abstractmethod
    def is_connected(self) -> bool:
        """True if the broker connection / session is active."""
        ...

    @abstractmethod
    async def connect(self) -> None:
        """Establish connection / validate credentials."""
        ...

    @abstractmethod
    async def disconnect(self) -> None:
        """Clean up connection resources."""
        ...

    # ── Orders ────────────────────────────────────────────────────────────────

    @abstractmethod
    async def place_order(self, request: OrderRequest) -> OrderResult:
        """
        Place a new order.
        Raises: OrderRejectedError, InsufficientFundsError, RateLimitError, NetworkError
        """
        ...

    @abstractmethod
    async def modify_order(
        self,
        broker_order_id: str,
        *,
        quantity: Optional[int] = None,
        price: Optional[float] = None,
        trigger_price: Optional[float] = None,
        order_type: Optional[str] = None,
        validity: Optional[str] = None,
    ) -> OrderResult:
        """Modify a pending/open order."""
        ...

    @abstractmethod
    async def cancel_order(self, broker_order_id: str, variety: str = "regular") -> OrderResult:
        """Cancel an open order."""
        ...

    # ── Queries ───────────────────────────────────────────────────────────────

    @abstractmethod
    async def get_order(self, broker_order_id: str) -> OrderBookEntry:
        """Fetch a single order's current state."""
        ...

    @abstractmethod
    async def get_order_book(self) -> list[OrderBookEntry]:
        """Fetch today's full order book."""
        ...

    @abstractmethod
    async def get_positions(self) -> list[Position]:
        """Fetch all current positions (day + net)."""
        ...

    @abstractmethod
    async def get_account_info(self) -> AccountInfo:
        """Fetch margin / funds summary."""
        ...

    # ── Optional capability ───────────────────────────────────────────────────

    async def get_holdings(self) -> list[Position]:
        """
        Fetch long-term holdings (CNC positions).
        Default: returns empty list (not all brokers support this separately).
        """
        return []
