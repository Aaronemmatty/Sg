"""Order service — the single entry point for all order operations."""
from __future__ import annotations

import secrets
from typing import Optional

from app.brokers.factory import get_broker
from app.brokers.interface import BrokerError, OrderRejectedError
from app.core.logging import get_logger
from app.core.types import (
    AccountInfo, OrderBookEntry, OrderRequest,
    OrderResult, Position,
)
from app.risk.engine import RiskViolation, get_risk_engine

log = get_logger(__name__)


class OrderService:
    async def place_order(self, request: OrderRequest) -> OrderResult:
        # Generate idempotency key if caller didn't supply one
        if not request.client_order_id:
            request.client_order_id = f"SG-{secrets.token_hex(8).upper()}"

        broker = await get_broker()
        risk   = get_risk_engine()

        # ── Pre-trade risk check ──────────────────────────────────────────────
        check = await risk.pre_trade_check(request, broker)
        if not check.passed:
            violations = "; ".join(str(v) for v in check.violations)
            raise OrderRejectedError(
                f"Pre-trade risk check failed: {violations}",
                reason="risk_violation",
            )

        if check.warnings:
            for w in check.warnings:
                log.warning("pre_trade_warning", symbol=request.symbol, warning=w)

        # ── Execute order ─────────────────────────────────────────────────────
        result = await broker.place_order(request)

        # ── Post-trade check ──────────────────────────────────────────────────
        await risk.post_trade_check(request, result, broker)

        log.info(
            "order_placed",
            client_order_id=request.client_order_id,
            broker_order_id=result.broker_order_id,
            symbol=request.symbol,
            side=request.side.value,
            status=result.status.value,
        )
        return result

    async def cancel_order(self, broker_order_id: str, variety: str = "regular") -> OrderResult:
        broker = await get_broker()
        result = await broker.cancel_order(broker_order_id, variety)
        log.info("order_cancelled", broker_order_id=broker_order_id)
        return result

    async def modify_order(
        self,
        broker_order_id: str,
        **kwargs,
    ) -> OrderResult:
        broker = await get_broker()
        result = await broker.modify_order(broker_order_id, **kwargs)
        log.info("order_modified", broker_order_id=broker_order_id)
        return result

    async def get_order(self, broker_order_id: str) -> OrderBookEntry:
        broker = await get_broker()
        return await broker.get_order(broker_order_id)

    async def get_order_book(self) -> list[OrderBookEntry]:
        broker = await get_broker()
        return await broker.get_order_book()

    async def get_positions(self) -> list[Position]:
        broker = await get_broker()
        return await broker.get_positions()

    async def get_account_info(self) -> AccountInfo:
        broker = await get_broker()
        return await broker.get_account_info()
