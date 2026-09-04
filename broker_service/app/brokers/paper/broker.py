"""
Paper Broker — realistic order simulation for NSE equities.

Fill simulation:
  MARKET orders → fill immediately at last_price ± slippage
  LIMIT orders  → fill when market price crosses limit price
  SL / SL-M     → fill when trigger is hit

All state is in-memory (positions, orders, cash).
Persisted to Redis so it survives restarts.
"""
from __future__ import annotations

import asyncio
import json
import secrets
import time
from datetime import UTC, datetime
from typing import Optional

from app.brokers.interface import BrokerInterface, OrderRejectedError, InsufficientFundsError
from app.core.config import get_settings
from app.core.logging import get_logger
from app.core.redis import get_redis
from app.core.types import (
    AccountInfo,
    OrderBookEntry,
    OrderRequest,
    OrderResult,
    OrderStatus,
    OrderType,
    OrderSide,
    Position,
)

settings = get_settings()
log = get_logger(__name__)

_PAPER_STATE_KEY = "paper_broker:state"


class PaperBroker(BrokerInterface):
    """
    Simulated broker — perfect for strategy testing without real capital.

    State stored in Redis so positions/orders persist across restarts.
    """

    def __init__(self) -> None:
        self._cash: float = settings.PAPER_INITIAL_CAPITAL_INR
        self._positions: dict[str, dict] = {}   # symbol → position dict
        self._orders: dict[str, dict] = {}       # broker_order_id → order dict
        self._day_pnl: float = 0.0
        self._connected = False
        self._fill_task: Optional[asyncio.Task] = None

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    @property
    def broker_name(self) -> str:
        return "paper"

    @property
    def is_connected(self) -> bool:
        return self._connected

    async def connect(self) -> None:
        await self._load_state()
        self._fill_task = asyncio.create_task(
            self._fill_loop(), name="paper-fill-loop"
        )
        self._connected = True
        log.info("paper_broker_connected",
                 cash=self._cash, positions=len(self._positions))

    async def disconnect(self) -> None:
        self._connected = False
        if self._fill_task:
            self._fill_task.cancel()
        await self._save_state()
        log.info("paper_broker_disconnected")

    # ── Orders ────────────────────────────────────────────────────────────────

    async def place_order(self, request: OrderRequest) -> OrderResult:
        self._validate_order(request)

        broker_id = f"PAPER-{secrets.token_hex(6).upper()}"
        now = datetime.now(UTC)

        order = {
            "broker_order_id":    broker_id,
            "client_order_id":    request.client_order_id,
            "symbol":             request.symbol,
            "exchange":           request.exchange.value,
            "side":               request.side.value,
            "order_type":         request.order_type.value,
            "product":            request.product.value,
            "quantity":           request.quantity,
            "price":              request.price,
            "trigger_price":      request.trigger_price,
            "validity":           request.validity.value,
            "status":             OrderStatus.OPEN.value,
            "filled_quantity":    0,
            "average_price":      None,
            "pending_quantity":   request.quantity,
            "rejection_reason":   None,
            "placed_at":          now.isoformat(),
            "updated_at":         now.isoformat(),
            "tag":                request.tag,
        }
        self._orders[broker_id] = order

        # Market orders fill immediately
        if request.order_type == OrderType.MARKET:
            await asyncio.sleep(settings.PAPER_FILL_DELAY_MS / 1000)
            await self._try_fill(broker_id)

        await self._save_state()
        return self._order_to_result(order)

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
        order = self._orders.get(broker_order_id)
        if not order:
            raise OrderRejectedError(f"Order {broker_order_id} not found")
        if order["status"] not in (OrderStatus.OPEN.value, OrderStatus.PENDING.value):
            raise OrderRejectedError(f"Cannot modify order in status {order['status']}")

        if quantity:      order["quantity"] = quantity
        if price:         order["price"] = price
        if trigger_price: order["trigger_price"] = trigger_price
        if order_type:    order["order_type"] = order_type
        if validity:      order["validity"] = validity
        order["updated_at"] = datetime.now(UTC).isoformat()

        await self._save_state()
        return self._order_to_result(order)

    async def cancel_order(self, broker_order_id: str, variety: str = "regular") -> OrderResult:
        order = self._orders.get(broker_order_id)
        if not order:
            raise OrderRejectedError(f"Order {broker_order_id} not found")
        if order["status"] in (OrderStatus.COMPLETE.value, OrderStatus.CANCELLED.value):
            raise OrderRejectedError(f"Cannot cancel order in status {order['status']}")

        order["status"] = OrderStatus.CANCELLED.value
        order["pending_quantity"] = 0
        order["updated_at"] = datetime.now(UTC).isoformat()

        await self._save_state()
        return self._order_to_result(order)

    # ── Queries ───────────────────────────────────────────────────────────────

    async def get_order(self, broker_order_id: str) -> OrderBookEntry:
        order = self._orders.get(broker_order_id)
        if not order:
            from app.brokers.interface import BrokerError
            raise BrokerError(f"Order {broker_order_id} not found", "order_not_found")
        return self._order_to_book_entry(order)

    async def get_order_book(self) -> list[OrderBookEntry]:
        return [self._order_to_book_entry(o) for o in self._orders.values()]

    async def get_positions(self) -> list[Position]:
        return [self._dict_to_position(p) for p in self._positions.values()]

    async def get_account_info(self) -> AccountInfo:
        pos_value = sum(
            p["quantity"] * p["last_price"]
            for p in self._positions.values()
        )
        return AccountInfo(
            broker="paper",
            account_id="PAPER-ACCOUNT",
            available_cash=self._cash,
            used_margin=0.0,
            total_margin=self._cash + pos_value,
            net_value=self._cash + pos_value,
            day_pnl=self._day_pnl,
            positions_value=pos_value,
        )

    # ── Fill simulation ───────────────────────────────────────────────────────

    async def _fill_loop(self) -> None:
        """Check open limit/SL orders every second against last market price."""
        while self._connected:
            try:
                open_orders = [
                    o for o in self._orders.values()
                    if o["status"] == OrderStatus.OPEN.value
                    and o["order_type"] != "MARKET"
                ]
                for order in open_orders:
                    await self._try_fill(order["broker_order_id"])
            except asyncio.CancelledError:
                break
            except Exception as exc:
                log.error("paper_fill_loop_error", error=str(exc))
            await asyncio.sleep(1.0)

    async def _try_fill(self, broker_order_id: str) -> None:
        order = self._orders.get(broker_order_id)
        if not order or order["status"] != OrderStatus.OPEN.value:
            return

        market_price = await self._get_market_price(order["symbol"], order["exchange"])
        if market_price is None:
            return

        order_type = order["order_type"]
        side       = order["side"]
        price      = order.get("price")
        trigger    = order.get("trigger_price")

        should_fill = False
        fill_price  = market_price

        if order_type == "MARKET":
            should_fill = True
            # Apply slippage
            slippage = market_price * settings.PAPER_SLIPPAGE_PCT / 100
            fill_price = market_price + slippage if side == "BUY" else market_price - slippage

        elif order_type == "LIMIT":
            if side == "BUY" and market_price <= price:
                should_fill = True
                fill_price = price
            elif side == "SELL" and market_price >= price:
                should_fill = True
                fill_price = price

        elif order_type == "SL-M" and trigger:
            if side == "BUY" and market_price >= trigger:
                should_fill = True
                fill_price = market_price
            elif side == "SELL" and market_price <= trigger:
                should_fill = True
                fill_price = market_price

        elif order_type == "SL" and trigger and price:
            if side == "BUY" and market_price >= trigger:
                should_fill = True
                fill_price = price
            elif side == "SELL" and market_price <= trigger:
                should_fill = True
                fill_price = price

        if should_fill:
            await self._execute_fill(order, fill_price)

    async def _execute_fill(self, order: dict, fill_price: float) -> None:
        qty  = order["quantity"]
        side = order["side"]
        symbol = order["symbol"]
        total_value = fill_price * qty

        # Check capital for buys
        if side == "BUY":
            if total_value > self._cash:
                order["status"] = OrderStatus.REJECTED.value
                order["rejection_reason"] = "Insufficient paper capital"
                log.warning("paper_order_rejected_no_cash",
                            symbol=symbol, value=total_value, cash=self._cash)
                return
            self._cash -= total_value
        else:
            self._cash += total_value

        # Update position
        self._update_position(symbol, order["exchange"], order["product"],
                              side, qty, fill_price)

        # Update order state
        order["status"]          = OrderStatus.COMPLETE.value
        order["filled_quantity"] = qty
        order["pending_quantity"] = 0
        order["average_price"]   = fill_price
        order["updated_at"]      = datetime.now(UTC).isoformat()

        log.info("paper_order_filled",
                 broker_order_id=order["broker_order_id"],
                 symbol=symbol, side=side, qty=qty, price=fill_price)

        await self._save_state()

    def _update_position(
        self, symbol: str, exchange: str, product: str,
        side: str, qty: int, price: float
    ) -> None:
        key = f"{symbol}:{product}"
        pos = self._positions.get(key, {
            "symbol": symbol, "exchange": exchange, "product": product,
            "quantity": 0, "average_price": 0.0, "last_price": price,
            "pnl": 0.0, "day_pnl": 0.0, "value": 0.0,
            "buy_quantity": 0, "sell_quantity": 0,
            "buy_value": 0.0, "sell_value": 0.0,
        })

        if side == "BUY":
            total_cost = pos["average_price"] * pos["quantity"] + price * qty
            pos["quantity"]     += qty
            pos["buy_quantity"] += qty
            pos["buy_value"]    += price * qty
            pos["average_price"] = total_cost / pos["quantity"] if pos["quantity"] else price
        else:
            pos["quantity"]      -= qty
            pos["sell_quantity"] += qty
            pos["sell_value"]    += price * qty
            pnl = (price - pos["average_price"]) * qty
            pos["pnl"]     += pnl
            pos["day_pnl"] += pnl
            self._day_pnl  += pnl

        pos["last_price"] = price
        pos["value"]      = pos["quantity"] * price

        if pos["quantity"] == 0:
            self._positions.pop(key, None)
        else:
            self._positions[key] = pos

    async def _get_market_price(self, symbol: str, exchange: str) -> Optional[float]:
        """Read last price from Redis tick cache (published by market data service on DB 1)."""
        import redis.asyncio as redis_lib
        try:
            r = redis_lib.from_url("redis://127.0.0.1:6379/1")
            full_sym = f"{exchange}:{symbol}"
            raw = await r.get(f"tick:{full_sym}")
            if not raw:
                raw = await r.get(f"tick:{symbol}")
            await r.aclose()
            if raw:
                data = json.loads(raw)
                return float(data.get("last_price", 0)) or None
        except Exception:
            pass
        return None

    # ── Validation ────────────────────────────────────────────────────────────

    def _validate_order(self, request: OrderRequest) -> None:
        order_value = (request.price or 0) * request.quantity
        # Dynamic max order value = 20% of current paper cash (or initial capital fallback)
        max_order_val = max(self._cash, settings.ACCOUNT_CAPITAL_INR) * settings.MAX_ORDER_VALUE_PCT
        if order_value > max_order_val:
            raise OrderRejectedError(
                f"Order value ₹{order_value:,.0f} exceeds limit ₹{max_order_val:,.0f} "
                f"({settings.MAX_ORDER_VALUE_PCT*100:.0f}% of available cash)",
                reason="order_value_exceeded",
            )


    # ── Persistence ───────────────────────────────────────────────────────────

    async def _save_state(self) -> None:
        try:
            r = await get_redis()
            state = {
                "cash":       self._cash,
                "positions":  self._positions,
                "orders":     self._orders,
                "day_pnl":    self._day_pnl,
            }
            await r.set(_PAPER_STATE_KEY, json.dumps(state, default=str))
        except Exception as exc:
            log.error("paper_state_save_failed", error=str(exc))

    async def _load_state(self) -> None:
        try:
            r = await get_redis()
            raw = await r.get(_PAPER_STATE_KEY)
            if raw:
                state = json.loads(raw)
                self._cash       = float(state.get("cash", settings.PAPER_INITIAL_CAPITAL_INR))
                self._positions  = state.get("positions", {})
                self._orders     = state.get("orders", {})
                self._day_pnl    = float(state.get("day_pnl", 0.0))
                log.info("paper_state_loaded",
                         cash=self._cash, positions=len(self._positions))
        except Exception as exc:
            log.warning("paper_state_load_failed_using_defaults", error=str(exc))

    # ── Converters ────────────────────────────────────────────────────────────

    def _order_to_result(self, order: dict) -> OrderResult:
        return OrderResult(
            broker_order_id=order["broker_order_id"],
            client_order_id=order.get("client_order_id"),
            status=OrderStatus(order["status"]),
            symbol=order["symbol"],
            exchange=order["exchange"],
            side=order["side"],
            order_type=order["order_type"],
            quantity=order["quantity"],
            price=order.get("price"),
            trigger_price=order.get("trigger_price"),
            filled_quantity=order.get("filled_quantity", 0),
            average_price=order.get("average_price"),
            pending_quantity=order.get("pending_quantity", 0),
            rejection_reason=order.get("rejection_reason"),
            placed_at=datetime.fromisoformat(order["placed_at"]) if order.get("placed_at") else None,
            updated_at=datetime.fromisoformat(order["updated_at"]) if order.get("updated_at") else None,
        )

    def _order_to_book_entry(self, order: dict) -> OrderBookEntry:
        return OrderBookEntry(
            broker_order_id=order["broker_order_id"],
            symbol=order["symbol"],
            exchange=order["exchange"],
            side=order["side"],
            order_type=order["order_type"],
            product=order.get("product", "MIS"),
            quantity=order["quantity"],
            filled_quantity=order.get("filled_quantity", 0),
            pending_quantity=order.get("pending_quantity", 0),
            price=order.get("price"),
            trigger_price=order.get("trigger_price"),
            average_price=order.get("average_price"),
            status=OrderStatus(order["status"]),
            validity=order.get("validity", "DAY"),
            tag=order.get("tag"),
            placed_at=datetime.fromisoformat(order["placed_at"]) if order.get("placed_at") else None,
            updated_at=datetime.fromisoformat(order["updated_at"]) if order.get("updated_at") else None,
            rejection_reason=order.get("rejection_reason"),
        )

    def _dict_to_position(self, p: dict) -> Position:
        return Position(
            symbol=p["symbol"],
            exchange=p.get("exchange", "NSE"),
            product=p.get("product", "MIS"),
            quantity=p["quantity"],
            average_price=p["average_price"],
            last_price=p["last_price"],
            pnl=p.get("pnl", 0.0),
            day_pnl=p.get("day_pnl", 0.0),
            value=p.get("value", 0.0),
            buy_quantity=p.get("buy_quantity", 0),
            sell_quantity=p.get("sell_quantity", 0),
            buy_value=p.get("buy_value", 0.0),
            sell_value=p.get("sell_value", 0.0),
        )
