"""
Position Engine — core calculation logic for portfolio_management_service.

Responsibilities:
  - Apply buy fills: open FIFO lots, update position avg cost
  - Apply sell fills: consume lots FIFO, compute realized P&L
  - Recompute avg cost from remaining open lots after each transaction

Design decisions:
  - All operations run inside a single asyncpg transaction (atomicity)
  - Partial fills of existing orders update the same position record
  - Decimal throughout — no float arithmetic for monetary values
  - position.version is used for optimistic concurrency; the DB upsert
    increments it; if two concurrent fills race, Postgres serializes them
    via the ON CONFLICT update (last-write-wins is acceptable for fills
    since each fill carries its own idempotency guard via pm_processed_events)
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP

import asyncpg

from app.core.logging import get_logger
from app.core.metrics import (
    lots_closed_total,
    lots_opened_total,
    position_updates_total,
    realized_pnl_inr,
)
from app.db import repository as repo
from app.db.session import pool
from app.models.domain import (
    ExecutionEvent,
    Lot,
    LotConsumption,
    LotStatus,
    Position,
    TradeAction,
)

log = get_logger(__name__)

_INR_PRECISION = Decimal("0.01")


def _round_inr(value: Decimal) -> Decimal:
    return value.quantize(_INR_PRECISION, rounding=ROUND_HALF_UP)


async def apply_fill(event: ExecutionEvent) -> Position:
    """
    Apply an ORDER_FILLED or ORDER_PARTIALLY_FILLED event to the position
    and lot ledger. Runs as a single atomic transaction.

    Returns the updated Position (after DB write, before MTM refresh).
    """
    if event.avg_fill_price_inr is None or event.filled_quantity == 0:
        log.warning(
            "fill_event_has_no_price_or_qty",
            event_type=event.event_type,
            order_id=str(event.order_id),
        )
        raise ValueError(f"Fill event {event.order_id} has no fill price or zero quantity")

    fill_price = Decimal(str(event.avg_fill_price_inr))
    fill_qty = event.filled_quantity
    symbol = event.symbol

    async with pool.acquire() as conn:
        async with conn.transaction():
            current = await repo.get_position(symbol)
            if current is None:
                current = Position(symbol=symbol)

            if event.action == TradeAction.BUY:
                updated = await _apply_buy(
                    conn=conn,
                    position=current,
                    event=event,
                    fill_price=fill_price,
                    fill_qty=fill_qty,
                )
            else:
                updated = await _apply_sell(
                    conn=conn,
                    position=current,
                    event=event,
                    fill_price=fill_price,
                    fill_qty=fill_qty,
                )

            updated.last_trade_at = event.emitted_at
            await repo.upsert_position(updated, conn=conn)

            await repo.insert_trade_ledger_entry(
                event_id=event.order_id,   # order_id is unique per fill event
                order_id=event.order_id,
                symbol=symbol,
                action=event.action.value,
                filled_quantity=fill_qty,
                avg_fill_price_inr=float(fill_price),
                slippage_bps=event.slippage_bps,
                emitted_at=event.emitted_at,
                conn=conn,
            )

    position_updates_total.labels(action=event.action.value, symbol=symbol).inc()
    log.info(
        "fill_applied",
        symbol=symbol,
        action=event.action.value,
        qty=fill_qty,
        price=float(fill_price),
        net_qty=updated.net_quantity,
        realized_pnl=float(updated.realized_pnl_inr),
    )
    return updated


async def _apply_buy(
    *,
    conn: asyncpg.Connection,
    position: Position,
    event: ExecutionEvent,
    fill_price: Decimal,
    fill_qty: int,
) -> Position:
    """
    Open a new lot, recompute avg cost.

    avg_cost = sum(lot.remaining_qty * lot.cost_price) / total_remaining_qty
    """
    # Open new lot
    lot = Lot(
        symbol=event.symbol,
        order_id=event.order_id,
        execution_event_id=event.order_id,
        original_quantity=fill_qty,
        remaining_quantity=fill_qty,
        cost_price_inr=fill_price,
    )
    await repo.insert_lot(lot, conn=conn)
    lots_opened_total.labels(symbol=event.symbol).inc()

    # Recompute avg cost from all open lots (including the one just inserted)
    open_lots = await repo.get_open_lots(event.symbol, conn=conn)
    new_qty = position.net_quantity + fill_qty
    total_cost = sum(
        Decimal(str(l.remaining_quantity)) * l.cost_price_inr for l in open_lots
    )
    new_avg_cost = _round_inr(total_cost / Decimal(str(new_qty))) if new_qty > 0 else Decimal("0")

    position.net_quantity = new_qty
    position.avg_cost_inr = new_avg_cost
    return position


async def _apply_sell(
    *,
    conn: asyncpg.Connection,
    position: Position,
    event: ExecutionEvent,
    fill_price: Decimal,
    fill_qty: int,
) -> Position:
    """
    Consume open lots FIFO, compute realized P&L per lot consumed.

    If fill_qty > net_quantity (short selling), we record what we can
    against existing lots and log a warning — the platform v1 is long-only
    per strategy_service constraints, but we handle it defensively.
    """
    open_lots = await repo.get_open_lots(event.symbol, conn=conn)
    remaining_to_sell = fill_qty
    total_realized = Decimal("0")

    for lot in open_lots:
        if remaining_to_sell <= 0:
            break

        consumable = min(lot.remaining_quantity, remaining_to_sell)
        realized = _round_inr((fill_price - lot.cost_price_inr) * Decimal(str(consumable)))
        total_realized += realized

        consumption = LotConsumption(
            lot_id=lot.lot_id,
            qty_consumed=consumable,
            cost_price_inr=lot.cost_price_inr,
            sell_price_inr=fill_price,
            realized_pnl_inr=realized,
        )
        await repo.insert_lot_consumption(
            consumption,
            order_id=event.order_id,
            execution_event_id=event.order_id,
            symbol=event.symbol,
            conn=conn,
        )

        lot.remaining_quantity -= consumable
        remaining_to_sell -= consumable

        if lot.remaining_quantity == 0:
            lot.status = LotStatus.CLOSED
            lot.closed_at = datetime.now(timezone.utc)
            lots_closed_total.labels(symbol=event.symbol).inc()
        else:
            lot.status = LotStatus.PARTIALLY_CLOSED

        await repo.update_lot(lot, conn=conn)

    if remaining_to_sell > 0:
        log.warning(
            "sell_qty_exceeds_open_lots",
            symbol=event.symbol,
            order_id=str(event.order_id),
            excess_qty=remaining_to_sell,
        )

    new_qty = max(0, position.net_quantity - fill_qty)
    position.net_quantity = new_qty
    position.realized_pnl_inr = _round_inr(position.realized_pnl_inr + total_realized)

    # Recompute avg cost from remaining open lots
    if new_qty > 0:
        remaining_lots = await repo.get_open_lots(event.symbol, conn=conn)
        total_cost = sum(Decimal(str(l.remaining_quantity)) * l.cost_price_inr for l in remaining_lots)
        position.avg_cost_inr = _round_inr(total_cost / Decimal(str(new_qty)))
    else:
        position.avg_cost_inr = Decimal("0")

    # Track metric
    realized_pnl_inr.labels(symbol=event.symbol).inc(float(total_realized))

    return position
