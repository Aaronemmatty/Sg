"""
Zerodha Kite Broker Adapter.

Wraps the synchronous kiteconnect SDK in asyncio-friendly async methods
using a dedicated ThreadPoolExecutor. All broker-specific response
shapes are translated into the canonical domain types here.

Kite order varieties:
  - regular  : normal equity / F&O orders
  - amo      : after-market orders
  - co       : cover orders
  - iceberg  : iceberg orders

We only expose 'regular' variety for now (covers all NSE equity use-cases).
"""
from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from typing import Any, Optional
from zoneinfo import ZoneInfo

from kiteconnect import KiteConnect
from kiteconnect.exceptions import (
    InputException,
    NetworkException,
    OrderException,
    TokenException,
)
from tenacity import (
    AsyncRetrying,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential,
)

from app.brokers.circuit_breaker import CircuitBreaker, CircuitOpenError
from app.brokers.interface import (
    AuthenticationError,
    BrokerError,
    BrokerInterface,
    InsufficientFundsError,
    NetworkError,
    OrderRejectedError,
    RateLimitError,
)
from app.brokers.rate_limiter import BrokerRateLimiter
from app.core.config import get_settings
from app.core.logging import get_logger
from app.core.types import (
    AccountInfo,
    OrderBookEntry,
    OrderRequest,
    OrderResult,
    OrderStatus,
    Position,
)

settings = get_settings()
log = get_logger(__name__)
IST = ZoneInfo("Asia/Kolkata")

_KITE_STATUS_MAP: dict[str, OrderStatus] = {
    "PUT ORDER REQ RECEIVED": OrderStatus.PENDING,
    "VALIDATION PENDING":      OrderStatus.PENDING,
    "OPEN PENDING":            OrderStatus.PENDING,
    "OPEN":                    OrderStatus.OPEN,
    "COMPLETE":                OrderStatus.COMPLETE,
    "CANCELLED":               OrderStatus.CANCELLED,
    "CANCELLED AMO":           OrderStatus.CANCELLED,
    "REJECTED":                OrderStatus.REJECTED,
    "MODIFY PENDING":          OrderStatus.OPEN,
    "TRIGGER PENDING":         OrderStatus.TRIGGER_PENDING,
}


class KiteBroker(BrokerInterface):
    def __init__(self) -> None:
        from app.brokers.factory import verify_live_trading_guard
        verify_live_trading_guard()

        self._kite = KiteConnect(
            api_key=settings.KITE_API_KEY,
            access_token=settings.KITE_ACCESS_TOKEN,
        )
        self._executor  = ThreadPoolExecutor(
            max_workers=settings.KITE_EXECUTOR_WORKERS,
            thread_name_prefix="kite-sdk",
        )
        self._cb        = CircuitBreaker("kite")
        self._rl        = BrokerRateLimiter("kite")
        self._connected = False

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    @property
    def broker_name(self) -> str:
        return "kite"

    @property
    def is_connected(self) -> bool:
        return self._connected

    async def connect(self) -> None:
        """Validate credentials by fetching profile."""
        try:
            await self._run(self._kite.profile)
            self._connected = True
            log.info("kite_broker_connected")
        except Exception as exc:
            self._connected = False
            raise AuthenticationError(f"Kite auth failed: {exc}") from exc

    async def disconnect(self) -> None:
        self._connected = False
        self._executor.shutdown(wait=False)
        log.info("kite_broker_disconnected")

    # ── Orders ────────────────────────────────────────────────────────────────

    async def place_order(self, request: OrderRequest) -> OrderResult:
        await self._rl.acquire(is_order=True)

        params = _order_request_to_kite(request)
        log.info("kite_place_order", symbol=request.symbol, side=request.side,
                 qty=request.quantity, type=request.order_type)

        raw = await self._execute_with_retry(
            self._kite.place_order, variety="regular", **params
        )
        # Kite returns {"order_id": "..."} on success
        broker_id = raw if isinstance(raw, str) else raw.get("order_id", str(raw))

        # Fetch full order details to return complete OrderResult
        order = await self.get_order(broker_id)
        result = _order_book_entry_to_result(order)
        result.client_order_id = request.client_order_id
        log.info("kite_order_placed", broker_order_id=broker_id, symbol=request.symbol)
        return result

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
        await self._rl.acquire(is_order=True)

        params: dict[str, Any] = {"order_id": broker_order_id, "variety": "regular"}
        if quantity:      params["quantity"]      = quantity
        if price:         params["price"]         = price
        if trigger_price: params["trigger_price"] = trigger_price
        if order_type:    params["order_type"]    = order_type
        if validity:      params["validity"]      = validity

        await self._execute_with_retry(self._kite.modify_order, **params)
        order = await self.get_order(broker_order_id)
        return _order_book_entry_to_result(order)

    async def cancel_order(self, broker_order_id: str, variety: str = "regular") -> OrderResult:
        await self._rl.acquire(is_order=True)
        await self._execute_with_retry(
            self._kite.cancel_order,
            variety=variety,
            order_id=broker_order_id,
        )
        order = await self.get_order(broker_order_id)
        return _order_book_entry_to_result(order)

    # ── Queries ───────────────────────────────────────────────────────────────

    async def get_order(self, broker_order_id: str) -> OrderBookEntry:
        await self._rl.acquire()
        orders = await self._execute_with_retry(
            self._kite.order_history, order_id=broker_order_id
        )
        if not orders:
            raise BrokerError(f"Order {broker_order_id} not found", "order_not_found")
        # Kite returns list of order history — take latest
        raw = orders[-1]
        return _parse_order(raw)

    async def get_order_book(self) -> list[OrderBookEntry]:
        await self._rl.acquire()
        raw_orders = await self._execute_with_retry(self._kite.orders)
        return [_parse_order(o) for o in (raw_orders or [])]

    async def get_positions(self) -> list[Position]:
        await self._rl.acquire()
        raw = await self._execute_with_retry(self._kite.positions)
        positions = []
        for p in (raw.get("net", []) if raw else []):
            positions.append(_parse_position(p))
        return positions

    async def get_holdings(self) -> list[Position]:
        await self._rl.acquire()
        raw = await self._execute_with_retry(self._kite.holdings)
        return [_parse_holding(h) for h in (raw or [])]

    async def get_account_info(self) -> AccountInfo:
        await self._rl.acquire()
        raw = await self._execute_with_retry(self._kite.margins)
        return _parse_margins(raw)

    # ── Internal helpers ──────────────────────────────────────────────────────

    async def _run(self, fn, *args, **kwargs) -> Any:
        """Run a sync Kite SDK call in the thread pool."""
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(self._executor, lambda: fn(*args, **kwargs))

    async def _execute_with_retry(self, fn, *args, **kwargs) -> Any:
        """Retry + circuit breaker wrapper for all SDK calls."""
        async def _attempt():
            try:
                return await self._run(fn, *args, **kwargs)
            except TokenException as e:
                raise AuthenticationError(str(e)) from e
            except InputException as e:
                raise OrderRejectedError(str(e), reason=str(e)) from e
            except NetworkException as e:
                raise NetworkError(str(e)) from e
            except OrderException as e:
                if "insufficient" in str(e).lower():
                    raise InsufficientFundsError(str(e)) from e
                raise OrderRejectedError(str(e)) from e
            except Exception as e:
                raise BrokerError(str(e), retryable=True) from e

        async def _with_cb():
            return await self._cb.call(_attempt)

        async for attempt in AsyncRetrying(
            stop=stop_after_attempt(settings.RETRY_MAX_ATTEMPTS),
            wait=wait_exponential(
                min=settings.RETRY_MIN_WAIT_S,
                max=settings.RETRY_MAX_WAIT_S,
            ),
            retry=retry_if_exception(lambda e: isinstance(e, BrokerError) and e.retryable),
            reraise=True,
        ):
            with attempt:
                return await _with_cb()


# ── Parsers ───────────────────────────────────────────────────────────────────

def _order_request_to_kite(req: OrderRequest) -> dict:
    params: dict[str, Any] = {
        "tradingsymbol": req.symbol,
        "exchange":      req.exchange.value,
        "transaction_type": req.side.value,
        "order_type":    req.order_type.value.replace("-", ""),  # SL-M → SLM
        "product":       req.product.value,
        "quantity":      req.quantity,
        "validity":      req.validity.value,
    }
    if req.price:         params["price"]              = req.price
    if req.trigger_price: params["trigger_price"]      = req.trigger_price
    if req.disclosed_quantity: params["disclosed_quantity"] = req.disclosed_quantity
    if req.tag:           params["tag"]                = req.tag[:8]
    return params


def _parse_order(raw: dict) -> OrderBookEntry:
    status_str = (raw.get("status") or "").upper()
    status = _KITE_STATUS_MAP.get(status_str, OrderStatus.PENDING)

    def _dt(v) -> Optional[datetime]:
        if not v:
            return None
        if isinstance(v, datetime):
            return v.replace(tzinfo=IST)
        try:
            return datetime.fromisoformat(str(v)).replace(tzinfo=IST)
        except Exception:
            return None

    return OrderBookEntry(
        broker_order_id=str(raw.get("order_id", "")),
        symbol=raw.get("tradingsymbol", ""),
        exchange=raw.get("exchange", "NSE"),
        side=raw.get("transaction_type", ""),
        order_type=raw.get("order_type", ""),
        product=raw.get("product", ""),
        quantity=int(raw.get("quantity", 0)),
        filled_quantity=int(raw.get("filled_quantity", 0)),
        pending_quantity=int(raw.get("pending_quantity", 0)),
        price=float(raw["price"]) if raw.get("price") else None,
        trigger_price=float(raw["trigger_price"]) if raw.get("trigger_price") else None,
        average_price=float(raw["average_price"]) if raw.get("average_price") else None,
        status=status,
        validity=raw.get("validity", "DAY"),
        tag=raw.get("tag"),
        placed_at=_dt(raw.get("order_timestamp")),
        updated_at=_dt(raw.get("exchange_update_timestamp")),
        rejection_reason=raw.get("status_message"),
    )


def _order_book_entry_to_result(entry: OrderBookEntry) -> OrderResult:
    return OrderResult(
        broker_order_id=entry.broker_order_id,
        client_order_id=None,
        status=entry.status,
        symbol=entry.symbol,
        exchange=entry.exchange,
        side=entry.side,
        order_type=entry.order_type,
        quantity=entry.quantity,
        price=entry.price,
        trigger_price=entry.trigger_price,
        filled_quantity=entry.filled_quantity,
        average_price=entry.average_price,
        pending_quantity=entry.pending_quantity,
        rejection_reason=entry.rejection_reason,
        placed_at=entry.placed_at,
        updated_at=entry.updated_at,
    )


def _parse_position(raw: dict) -> Position:
    qty = int(raw.get("quantity", 0))
    ltp = float(raw.get("last_price", 0))
    avg = float(raw.get("average_price", 0))
    return Position(
        symbol=raw.get("tradingsymbol", ""),
        exchange=raw.get("exchange", "NSE"),
        product=raw.get("product", ""),
        quantity=qty,
        average_price=avg,
        last_price=ltp,
        pnl=float(raw.get("pnl", 0)),
        day_pnl=float(raw.get("day_pnl", 0)),
        value=qty * ltp,
        buy_quantity=int(raw.get("buy_quantity", 0)),
        sell_quantity=int(raw.get("sell_quantity", 0)),
        buy_value=float(raw.get("buy_value", 0)),
        sell_value=float(raw.get("sell_value", 0)),
        multiplier=int(raw.get("multiplier", 1)),
        close_price=float(raw.get("close_price", 0)),
    )


def _parse_holding(raw: dict) -> Position:
    qty = int(raw.get("quantity", 0))
    ltp = float(raw.get("last_price", 0))
    avg = float(raw.get("average_price", 0))
    return Position(
        symbol=raw.get("tradingsymbol", ""),
        exchange=raw.get("exchange", "NSE"),
        product="CNC",
        quantity=qty,
        average_price=avg,
        last_price=ltp,
        pnl=float(raw.get("pnl", 0)),
        day_pnl=0.0,
        value=qty * ltp,
    )


def _parse_margins(raw: dict) -> AccountInfo:
    equity = raw.get("equity", {}) if raw else {}
    net    = equity.get("net", 0)
    avail  = equity.get("available", {})
    used   = equity.get("utilised", {})
    return AccountInfo(
        broker="kite",
        account_id=settings.KITE_API_KEY[:8] + "****",
        available_cash=float(avail.get("cash", 0)),
        used_margin=float(used.get("debits", 0)),
        total_margin=float(net),
        net_value=float(net),
        day_pnl=0.0,
        positions_value=0.0,
        raw=raw or {},
    )
