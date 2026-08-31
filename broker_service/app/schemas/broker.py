"""API request/response schemas — broker service."""
from __future__ import annotations

from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field


class PlaceOrderRequest(BaseModel):
    symbol: str = Field(..., description="Trading symbol e.g. RELIANCE")
    exchange: str = Field("NSE", description="NSE or BSE")
    side: str = Field(..., description="BUY or SELL")
    order_type: str = Field(..., description="MARKET | LIMIT | SL | SL-M")
    product: str = Field(..., description="CNC | MIS | NRML")
    quantity: int = Field(..., gt=0)
    price: Optional[float] = Field(None, description="Required for LIMIT/SL")
    trigger_price: Optional[float] = Field(None, description="Required for SL/SL-M")
    validity: str = Field("DAY", description="DAY | IOC")
    disclosed_quantity: Optional[int] = None
    tag: Optional[str] = Field(None, max_length=8)
    client_order_id: Optional[str] = None


class ModifyOrderRequest(BaseModel):
    quantity: Optional[int] = Field(None, gt=0)
    price: Optional[float] = None
    trigger_price: Optional[float] = None
    order_type: Optional[str] = None
    validity: Optional[str] = None


class OrderResultResponse(BaseModel):
    broker_order_id: str
    client_order_id: Optional[str]
    status: str
    symbol: str
    exchange: str
    side: str
    order_type: str
    quantity: int
    price: Optional[float]
    trigger_price: Optional[float]
    filled_quantity: int
    average_price: Optional[float]
    pending_quantity: int
    rejection_reason: Optional[str]
    placed_at: Optional[datetime]
    updated_at: Optional[datetime]


class OrderBookResponse(BaseModel):
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
    status: str
    validity: str
    tag: Optional[str]
    placed_at: Optional[datetime]
    updated_at: Optional[datetime]
    rejection_reason: Optional[str]


class PositionResponse(BaseModel):
    symbol: str
    exchange: str
    product: str
    quantity: int
    average_price: float
    last_price: float
    pnl: float
    day_pnl: float
    value: float
    buy_quantity: int
    sell_quantity: int


class AccountInfoResponse(BaseModel):
    broker: str
    account_id: str
    available_cash: float
    used_margin: float
    total_margin: float
    net_value: float
    day_pnl: float
    positions_value: float
    currency: str


class RiskStatusResponse(BaseModel):
    daily_pnl: float
    daily_loss_limit: float
    kill_switch_active: bool
    daily_order_counts: dict[str, int]
    last_reset: str


class BrokerStatusResponse(BaseModel):
    broker: str
    mode: str
    connected: bool
    circuit_breaker: Optional[dict]
    rate_limiter: Optional[dict]


class OkResponse(BaseModel):
    ok: bool = True
    message: str = "Success"
