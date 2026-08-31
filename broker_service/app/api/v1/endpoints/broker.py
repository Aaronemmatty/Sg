"""Broker API endpoints — orders, positions, account, risk, status."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Path, status

from app.auth import get_current_user, require_any_role
from app.brokers.factory import get_broker
from app.brokers.interface import BrokerError, OrderRejectedError, InsufficientFundsError
from app.core.config import get_settings
from app.core.types import Exchange, OrderRequest, OrderSide, OrderType, ProductType, Validity
from app.risk.engine import get_risk_engine
from app.schemas.broker import (
    AccountInfoResponse, BrokerStatusResponse, ModifyOrderRequest,
    OkResponse, OrderBookResponse, OrderResultResponse,
    PlaceOrderRequest, PositionResponse, RiskStatusResponse,
)
from app.services.order import OrderService
from sg_security.validation import validate_symbol

settings = get_settings()
router = APIRouter(prefix="/broker", tags=["Broker"])


def _svc() -> OrderService:
    return OrderService()


def _map_result(r) -> OrderResultResponse:
    return OrderResultResponse(
        broker_order_id=r.broker_order_id,
        client_order_id=r.client_order_id,
        status=r.status.value,
        symbol=r.symbol, exchange=r.exchange,
        side=r.side, order_type=r.order_type,
        quantity=r.quantity, price=r.price,
        trigger_price=r.trigger_price,
        filled_quantity=r.filled_quantity,
        average_price=r.average_price,
        pending_quantity=r.pending_quantity,
        rejection_reason=r.rejection_reason,
        placed_at=r.placed_at, updated_at=r.updated_at,
    )


# ── Orders ────────────────────────────────────────────────────────────────────

@router.post("/orders", response_model=OrderResultResponse,
             status_code=status.HTTP_201_CREATED, summary="Place a new order")
async def place_order(
    body: PlaceOrderRequest,
    _user = Depends(require_any_role(["trader", "admin"])),
) -> OrderResultResponse:
    try:
        request = OrderRequest(
            symbol=body.symbol,
            exchange=Exchange(body.exchange),
            side=OrderSide(body.side),
            order_type=OrderType(body.order_type.replace("SL-M", "SL_M")),
            product=ProductType(body.product),
            quantity=body.quantity,
            price=body.price,
            trigger_price=body.trigger_price,
            validity=Validity(body.validity),
            disclosed_quantity=body.disclosed_quantity,
            tag=body.tag,
            client_order_id=body.client_order_id,
        )
    except (ValueError, KeyError) as e:
        raise HTTPException(status_code=422, detail=str(e))

    try:
        result = await _svc().place_order(request)
    except OrderRejectedError as e:
        raise HTTPException(status_code=400, detail=e.message)
    except InsufficientFundsError as e:
        raise HTTPException(status_code=402, detail=e.message)
    except BrokerError as e:
        raise HTTPException(status_code=503 if e.retryable else 400, detail=e.message)

    return _map_result(result)


@router.put("/orders/{broker_order_id}", response_model=OrderResultResponse,
            summary="Modify an open order")
async def modify_order(
    broker_order_id: str,
    body: ModifyOrderRequest,
    _user = Depends(require_any_role(["trader", "admin"])),
) -> OrderResultResponse:
    try:
        result = await _svc().modify_order(
            broker_order_id,
            quantity=body.quantity,
            price=body.price,
            trigger_price=body.trigger_price,
            order_type=body.order_type,
            validity=body.validity,
        )
    except BrokerError as e:
        raise HTTPException(status_code=400, detail=e.message)
    return _map_result(result)


@router.delete("/orders/{broker_order_id}", response_model=OrderResultResponse,
               summary="Cancel an open order")
async def cancel_order(
    broker_order_id: str,
    variety: str = "regular",
    _user = Depends(require_any_role(["trader", "admin"])),
) -> OrderResultResponse:
    try:
        result = await _svc().cancel_order(broker_order_id, variety)
    except BrokerError as e:
        raise HTTPException(status_code=400, detail=e.message)
    return _map_result(result)


@router.get("/orders", response_model=list[OrderBookResponse], summary="Get today's order book")
async def get_order_book(_user = Depends(get_current_user)) -> list[OrderBookResponse]:
    orders = await _svc().get_order_book()
    return [
        OrderBookResponse(
            broker_order_id=o.broker_order_id,
            symbol=o.symbol, exchange=o.exchange,
            side=o.side, order_type=o.order_type, product=o.product,
            quantity=o.quantity, filled_quantity=o.filled_quantity,
            pending_quantity=o.pending_quantity,
            price=o.price, trigger_price=o.trigger_price,
            average_price=o.average_price,
            status=o.status.value, validity=o.validity,
            tag=o.tag, placed_at=o.placed_at, updated_at=o.updated_at,
            rejection_reason=o.rejection_reason,
        )
        for o in orders
    ]


@router.get("/orders/{broker_order_id}", response_model=OrderBookResponse,
            summary="Get a specific order")
async def get_order(broker_order_id: str, _user = Depends(get_current_user)) -> OrderBookResponse:
    try:
        o = await _svc().get_order(broker_order_id)
    except BrokerError as e:
        raise HTTPException(status_code=404, detail=e.message)
    return OrderBookResponse(
        broker_order_id=o.broker_order_id,
        symbol=o.symbol, exchange=o.exchange,
        side=o.side, order_type=o.order_type, product=o.product,
        quantity=o.quantity, filled_quantity=o.filled_quantity,
        pending_quantity=o.pending_quantity,
        price=o.price, trigger_price=o.trigger_price,
        average_price=o.average_price,
        status=o.status.value, validity=o.validity,
        tag=o.tag, placed_at=o.placed_at, updated_at=o.updated_at,
        rejection_reason=o.rejection_reason,
    )


# ── Positions & Account ───────────────────────────────────────────────────────

@router.get("/positions", response_model=list[PositionResponse], summary="Get current positions")
async def get_positions(_user = Depends(get_current_user)) -> list[PositionResponse]:
    positions = await _svc().get_positions()
    return [
        PositionResponse(
            symbol=p.symbol, exchange=p.exchange, product=p.product,
            quantity=p.quantity, average_price=p.average_price,
            last_price=p.last_price, pnl=p.pnl, day_pnl=p.day_pnl,
            value=p.value, buy_quantity=p.buy_quantity, sell_quantity=p.sell_quantity,
        )
        for p in positions
    ]


@router.get("/positions/{symbol}", response_model=PositionResponse, summary="Get one position by symbol")
async def get_position(symbol: str = Path(...), _user = Depends(get_current_user)) -> PositionResponse:
    symbol = validate_symbol(symbol)
    positions = await _svc().get_positions()
    for position in positions:
        if position.symbol == symbol:
            return PositionResponse(
                symbol=position.symbol,
                exchange=position.exchange,
                product=position.product,
                quantity=position.quantity,
                average_price=position.average_price,
                last_price=position.last_price,
                pnl=position.pnl,
                day_pnl=position.day_pnl,
                value=position.value,
                buy_quantity=position.buy_quantity,
                sell_quantity=position.sell_quantity,
            )
    raise HTTPException(status_code=404, detail=f"Position not found: {symbol}")


@router.get("/account", response_model=AccountInfoResponse, summary="Get account / margin info")
async def get_account(_user = Depends(get_current_user)) -> AccountInfoResponse:
    info = await _svc().get_account_info()
    return AccountInfoResponse(
        broker=info.broker, account_id=info.account_id,
        available_cash=info.available_cash, used_margin=info.used_margin,
        total_margin=info.total_margin, net_value=info.net_value,
        day_pnl=info.day_pnl, positions_value=info.positions_value,
        currency=info.currency,
    )


# ── Risk ──────────────────────────────────────────────────────────────────────

@router.get("/risk/status", response_model=RiskStatusResponse, summary="Risk engine status")
async def risk_status(_user = Depends(get_current_user)) -> RiskStatusResponse:
    return RiskStatusResponse(**get_risk_engine().get_status())


@router.post("/risk/reset-daily", response_model=OkResponse,
             summary="Reset daily risk counters (call at market open)")
async def reset_daily_risk(_user = Depends(require_any_role(["trader", "admin"]))) -> OkResponse:
    get_risk_engine().reset_daily()
    return OkResponse(message="Daily risk counters reset.")


# ── Broker status ─────────────────────────────────────────────────────────────

@router.get("/status", response_model=BrokerStatusResponse, summary="Broker connection status")
async def broker_status(_user = Depends(get_current_user)) -> BrokerStatusResponse:
    broker = await get_broker()
    cb_info = None
    rl_info = None

    if hasattr(broker, "_cb"):
        cb_info = broker._cb.to_dict()  # type: ignore[attr-defined]
    if hasattr(broker, "_rl"):
        rl_info = broker._rl.status()  # type: ignore[attr-defined]

    return BrokerStatusResponse(
        broker=broker.broker_name,
        mode=settings.BROKER_MODE,
        connected=broker.is_connected,
        circuit_breaker=cb_info,
        rate_limiter=rl_info,
    )
