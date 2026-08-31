"""Broker-agnostic domain types — the canonical language of the abstraction layer."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional


class OrderType(str, Enum):
    MARKET = "MARKET"
    LIMIT  = "LIMIT"
    SL     = "SL"        # Stop-Loss with trigger price
    SL_M   = "SL-M"      # Stop-Loss Market


class OrderSide(str, Enum):
    BUY  = "BUY"
    SELL = "SELL"


class ProductType(str, Enum):
    CNC   = "CNC"    # Delivery (equity)
    MIS   = "MIS"    # Intraday
    NRML  = "NRML"   # F&O normal


class Exchange(str, Enum):
    NSE = "NSE"
    BSE = "BSE"


class OrderStatus(str, Enum):
    PENDING          = "PENDING"
    OPEN             = "OPEN"
    COMPLETE         = "COMPLETE"
    CANCELLED        = "CANCELLED"
    REJECTED         = "REJECTED"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    TRIGGER_PENDING  = "TRIGGER_PENDING"


class Validity(str, Enum):
    DAY = "DAY"
    IOC = "IOC"   # Immediate or Cancel
    TTL = "TTL"   # Time-to-live (Kite)


@dataclass
class OrderRequest:
    """Broker-agnostic order placement request."""
    symbol: str                         # e.g. "RELIANCE"
    exchange: Exchange
    side: OrderSide
    order_type: OrderType
    product: ProductType
    quantity: int
    price: Optional[float] = None       # Required for LIMIT, SL
    trigger_price: Optional[float] = None   # Required for SL, SL-M
    validity: Validity = Validity.DAY
    disclosed_quantity: Optional[int] = None
    tag: Optional[str] = None           # Strategy tag (max 8 chars for Kite)
    # Internal tracking
    client_order_id: Optional[str] = None   # Our idempotency key

    def __post_init__(self):
        if self.order_type in (OrderType.LIMIT, OrderType.SL) and self.price is None:
            raise ValueError(f"price is required for {self.order_type}")
        if self.order_type in (OrderType.SL, OrderType.SL_M) and self.trigger_price is None:
            raise ValueError(f"trigger_price is required for {self.order_type}")
        if self.quantity <= 0:
            raise ValueError("quantity must be positive")


@dataclass
class OrderResult:
    """Result of a place/cancel/modify operation."""
    broker_order_id: str
    client_order_id: Optional[str]
    status: OrderStatus
    symbol: str
    exchange: str
    side: str
    order_type: str
    quantity: int
    price: Optional[float]
    trigger_price: Optional[float]
    filled_quantity: int = 0
    average_price: Optional[float] = None
    pending_quantity: int = 0
    cancelled_quantity: int = 0
    rejection_reason: Optional[str] = None
    placed_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    raw: dict = field(default_factory=dict)   # raw broker response


@dataclass
class Position:
    """Single position held by the account."""
    symbol: str
    exchange: str
    product: str
    quantity: int              # net quantity (positive=long, negative=short)
    average_price: float
    last_price: float
    pnl: float
    day_pnl: float
    value: float               # quantity * last_price
    buy_quantity: int = 0
    sell_quantity: int = 0
    buy_value: float = 0.0
    sell_value: float = 0.0
    multiplier: int = 1        # for F&O lot sizing
    close_price: float = 0.0


@dataclass
class AccountInfo:
    """Broker account / margin summary."""
    broker: str
    account_id: str
    available_cash: float
    used_margin: float
    total_margin: float
    net_value: float
    day_pnl: float
    positions_value: float
    currency: str = "INR"
    raw: dict = field(default_factory=dict)


@dataclass
class OrderBookEntry:
    """A single order from the broker order book."""
    broker_order_id: str
    symbol: str
    exchange: str
    side: str
    order_type: str
    product: str
    quantity: int
    filled_quantity: int
    pending_quantity: int
    price: Optional[float]
    trigger_price: Optional[float]
    average_price: Optional[float]
    status: OrderStatus
    validity: str
    tag: Optional[str]
    placed_at: Optional[datetime]
    updated_at: Optional[datetime]
    rejection_reason: Optional[str] = None
