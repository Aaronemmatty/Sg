"""
Persistence layer (asyncpg) for portfolio_management_service.

Design:
  - positions table:  one row per symbol, upserted on every fill
  - lots table:       FIFO lot ledger, immutable rows per buy fill
  - lot_consumptions: records how each sell consumed open lots (audit trail)
  - portfolio_config: single-row portfolio state (initial capital, cash balance)
  - portfolio_daily_returns: one NAV row per day (for Sharpe / drawdown calc)
  - portfolio_snapshots: periodic point-in-time snapshots (persisted JSON)
  - trade_ledger:     immutable fill event log (source of truth for trade stats)
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

import asyncpg

from app.core.logging import get_logger
from app.db.session import get_pool
from app.models.domain import (
    Lot,
    LotConsumption,
    LotStatus,
    Position,
    PortfolioSnapshot,
)

log = get_logger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Portfolio config (single-row, initialized on first startup)
# ─────────────────────────────────────────────────────────────────────────────

async def get_portfolio_config() -> dict[str, Any]:
    async with get_pool().acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM pm_portfolio_config LIMIT 1")
        if row is None:
            return {}
        return dict(row)


async def upsert_portfolio_config(
    *,
    initial_capital_inr: Decimal,
    cash_balance_inr: Decimal,
    day_open_value_inr: Decimal | None = None,
) -> None:
    async with get_pool().acquire() as conn:
        await conn.execute(
            """
            INSERT INTO pm_portfolio_config
                (config_id, initial_capital_inr, cash_balance_inr, day_open_value_inr, updated_at)
            VALUES (1, $1, $2, $3, now())
            ON CONFLICT (config_id) DO UPDATE
                SET initial_capital_inr  = EXCLUDED.initial_capital_inr,
                    cash_balance_inr     = EXCLUDED.cash_balance_inr,
                    day_open_value_inr   = COALESCE(EXCLUDED.day_open_value_inr, pm_portfolio_config.day_open_value_inr),
                    updated_at           = now()
            """,
            initial_capital_inr,
            cash_balance_inr,
            day_open_value_inr,
        )


# ─────────────────────────────────────────────────────────────────────────────
# Positions
# ─────────────────────────────────────────────────────────────────────────────

def _row_to_position(row: asyncpg.Record) -> Position:
    return Position(
        symbol=row["symbol"],
        net_quantity=row["net_quantity"],
        avg_cost_inr=Decimal(str(row["avg_cost_inr"])),
        market_price_inr=Decimal(str(row["market_price_inr"])) if row["market_price_inr"] is not None else None,
        market_value_inr=Decimal(str(row["market_value_inr"])),
        unrealized_pnl_inr=Decimal(str(row["unrealized_pnl_inr"])),
        realized_pnl_inr=Decimal(str(row["realized_pnl_inr"])),
        total_pnl_inr=Decimal(str(row["total_pnl_inr"])),
        day_pnl_inr=Decimal(str(row["day_pnl_inr"])),
        last_trade_at=row["last_trade_at"],
        last_mtm_at=row["last_mtm_at"],
        version=row["version"],
    )


async def get_position(symbol: str) -> Position | None:
    async with get_pool().acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM pm_positions WHERE symbol = $1",
            symbol.upper(),
        )
        return _row_to_position(row) if row else None


async def list_positions(include_flat: bool = False) -> list[Position]:
    """Return all positions; by default exclude flat (zero-qty) ones."""
    async with get_pool().acquire() as conn:
        if include_flat:
            rows = await conn.fetch("SELECT * FROM pm_positions ORDER BY symbol")
        else:
            rows = await conn.fetch(
                "SELECT * FROM pm_positions WHERE net_quantity != 0 ORDER BY symbol"
            )
        return [_row_to_position(r) for r in rows]


async def upsert_position(position: Position, *, conn: asyncpg.Connection | None = None) -> None:
    """
    Upsert position with optimistic locking (version check).
    Call inside a transaction when composing with lot inserts.
    """
    async def _do(c: asyncpg.Connection) -> None:
        await c.execute(
            """
            INSERT INTO pm_positions (
                symbol, net_quantity, avg_cost_inr, market_price_inr,
                market_value_inr, unrealized_pnl_inr, realized_pnl_inr,
                total_pnl_inr, day_pnl_inr, last_trade_at, last_mtm_at,
                version, updated_at
            ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12, now())
            ON CONFLICT (symbol) DO UPDATE
                SET net_quantity      = EXCLUDED.net_quantity,
                    avg_cost_inr      = EXCLUDED.avg_cost_inr,
                    market_price_inr  = EXCLUDED.market_price_inr,
                    market_value_inr  = EXCLUDED.market_value_inr,
                    unrealized_pnl_inr= EXCLUDED.unrealized_pnl_inr,
                    realized_pnl_inr  = EXCLUDED.realized_pnl_inr,
                    total_pnl_inr     = EXCLUDED.total_pnl_inr,
                    day_pnl_inr       = EXCLUDED.day_pnl_inr,
                    last_trade_at     = EXCLUDED.last_trade_at,
                    last_mtm_at       = EXCLUDED.last_mtm_at,
                    version           = pm_positions.version + 1,
                    updated_at        = now()
            """,
            position.symbol,
            position.net_quantity,
            position.avg_cost_inr,
            position.market_price_inr,
            position.market_value_inr,
            position.unrealized_pnl_inr,
            position.realized_pnl_inr,
            position.total_pnl_inr,
            position.day_pnl_inr,
            position.last_trade_at,
            position.last_mtm_at,
            position.version,
        )

    if conn is not None:
        await _do(conn)
    else:
        async with get_pool().acquire() as c:
            await _do(c)


async def update_position_mtm(
    symbol: str,
    market_price_inr: Decimal,
    market_value_inr: Decimal,
    unrealized_pnl_inr: Decimal,
    total_pnl_inr: Decimal,
    day_pnl_inr: Decimal,
) -> None:
    """Lightweight MTM-only update — does not touch cost basis or realized P&L."""
    async with get_pool().acquire() as conn:
        await conn.execute(
            """
            UPDATE pm_positions SET
                market_price_inr   = $1,
                market_value_inr   = $2,
                unrealized_pnl_inr = $3,
                total_pnl_inr      = $4,
                day_pnl_inr        = $5,
                last_mtm_at        = now(),
                version            = version + 1,
                updated_at         = now()
            WHERE symbol = $6
            """,
            market_price_inr,
            market_value_inr,
            unrealized_pnl_inr,
            total_pnl_inr,
            day_pnl_inr,
            symbol.upper(),
        )


# ─────────────────────────────────────────────────────────────────────────────
# FIFO Lots
# ─────────────────────────────────────────────────────────────────────────────

def _row_to_lot(row: asyncpg.Record) -> Lot:
    return Lot(
        lot_id=row["lot_id"],
        symbol=row["symbol"],
        order_id=row["order_id"],
        execution_event_id=row["execution_event_id"],
        original_quantity=row["original_quantity"],
        remaining_quantity=row["remaining_quantity"],
        cost_price_inr=Decimal(str(row["cost_price_inr"])),
        status=LotStatus(row["status"]),
        opened_at=row["opened_at"],
        closed_at=row["closed_at"],
    )


async def insert_lot(lot: Lot, *, conn: asyncpg.Connection | None = None) -> None:
    async def _do(c: asyncpg.Connection) -> None:
        await c.execute(
            """
            INSERT INTO pm_lots (
                lot_id, symbol, order_id, execution_event_id,
                original_quantity, remaining_quantity,
                cost_price_inr, status, opened_at
            ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9)
            ON CONFLICT (lot_id) DO NOTHING
            """,
            lot.lot_id,
            lot.symbol,
            lot.order_id,
            lot.execution_event_id,
            lot.original_quantity,
            lot.remaining_quantity,
            lot.cost_price_inr,
            lot.status.value,
            lot.opened_at,
        )

    if conn is not None:
        await _do(conn)
    else:
        async with get_pool().acquire() as c:
            await _do(c)


async def get_open_lots(symbol: str, *, conn: asyncpg.Connection | None = None) -> list[Lot]:
    """Return open/partially-closed lots for symbol, oldest first (FIFO order)."""
    async def _do(c: asyncpg.Connection) -> list[Lot]:
        rows = await c.fetch(
            """
            SELECT * FROM pm_lots
            WHERE symbol = $1 AND status IN ('OPEN', 'PARTIALLY_CLOSED')
            ORDER BY opened_at ASC
            """,
            symbol.upper(),
        )
        return [_row_to_lot(r) for r in rows]

    if conn is not None:
        return await _do(conn)
    async with get_pool().acquire() as c:
        return await _do(c)


async def update_lot(lot: Lot, *, conn: asyncpg.Connection | None = None) -> None:
    async def _do(c: asyncpg.Connection) -> None:
        await c.execute(
            """
            UPDATE pm_lots SET
                remaining_quantity = $1,
                status             = $2,
                closed_at          = $3,
                updated_at         = now()
            WHERE lot_id = $4
            """,
            lot.remaining_quantity,
            lot.status.value,
            lot.closed_at,
            lot.lot_id,
        )

    if conn is not None:
        await _do(conn)
    else:
        async with get_pool().acquire() as c:
            await _do(c)


# ─────────────────────────────────────────────────────────────────────────────
# Lot consumptions (sell-side audit)
# ─────────────────────────────────────────────────────────────────────────────

async def insert_lot_consumption(
    consumption: LotConsumption,
    *,
    order_id: uuid.UUID,
    execution_event_id: uuid.UUID,
    symbol: str,
    conn: asyncpg.Connection | None = None,
) -> None:
    async def _do(c: asyncpg.Connection) -> None:
        await c.execute(
            """
            INSERT INTO pm_lot_consumptions (
                consumption_id, lot_id, order_id, execution_event_id, symbol,
                qty_consumed, cost_price_inr, sell_price_inr, realized_pnl_inr, created_at
            ) VALUES (gen_random_uuid(), $1,$2,$3,$4,$5,$6,$7,$8, now())
            """,
            consumption.lot_id,
            order_id,
            execution_event_id,
            symbol.upper(),
            consumption.qty_consumed,
            consumption.cost_price_inr,
            consumption.sell_price_inr,
            consumption.realized_pnl_inr,
        )

    if conn is not None:
        await _do(conn)
    else:
        async with get_pool().acquire() as c:
            await _do(c)


# ─────────────────────────────────────────────────────────────────────────────
# Trade ledger (immutable fill event log)
# ─────────────────────────────────────────────────────────────────────────────

async def insert_trade_ledger_entry(
    *,
    event_id: uuid.UUID,
    order_id: uuid.UUID,
    symbol: str,
    action: str,
    filled_quantity: int,
    avg_fill_price_inr: float,
    slippage_bps: float | None,
    emitted_at: datetime,
    conn: asyncpg.Connection | None = None,
) -> None:
    async def _do(c: asyncpg.Connection) -> None:
        await c.execute(
            """
            INSERT INTO pm_trade_ledger (
                event_id, order_id, symbol, action,
                filled_quantity, avg_fill_price_inr,
                slippage_bps, emitted_at, recorded_at
            ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8, now())
            ON CONFLICT (event_id) DO NOTHING
            """,
            event_id,
            order_id,
            symbol.upper(),
            action,
            filled_quantity,
            avg_fill_price_inr,
            slippage_bps,
            emitted_at,
        )

    if conn is not None:
        await _do(conn)
    else:
        async with get_pool().acquire() as c:
            await _do(c)


async def list_trade_ledger(
    *,
    symbol: str | None = None,
    since: datetime | None = None,
    limit: int = 200,
    offset: int = 0,
) -> list[dict[str, Any]]:
    clauses: list[str] = []
    values: list[Any] = []
    idx = 1

    if symbol:
        clauses.append(f"symbol = ${idx}")
        values.append(symbol.upper())
        idx += 1
    if since:
        clauses.append(f"emitted_at >= ${idx}")
        values.append(since)
        idx += 1

    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    query = (
        f"SELECT * FROM pm_trade_ledger {where} "
        f"ORDER BY emitted_at DESC LIMIT ${idx} OFFSET ${idx + 1}"
    )
    values.extend([limit, offset])

    async with get_pool().acquire() as conn:
        rows = await conn.fetch(query, *values)
        return [dict(r) for r in rows]


# ─────────────────────────────────────────────────────────────────────────────
# Daily returns (for Sharpe / drawdown calculation)
# ─────────────────────────────────────────────────────────────────────────────

async def upsert_daily_return(
    *,
    date: str,               # ISO date "YYYY-MM-DD"
    nav_inr: Decimal,
    daily_return_pct: float,
) -> None:
    async with get_pool().acquire() as conn:
        await conn.execute(
            """
            INSERT INTO pm_daily_returns (date, nav_inr, daily_return_pct, recorded_at)
            VALUES ($1,$2,$3, now())
            ON CONFLICT (date) DO UPDATE
                SET nav_inr           = EXCLUDED.nav_inr,
                    daily_return_pct  = EXCLUDED.daily_return_pct,
                    recorded_at       = now()
            """,
            date,
            nav_inr,
            daily_return_pct,
        )


async def get_daily_returns(*, days: int = 252) -> list[dict[str, Any]]:
    """Return the most recent `days` daily return rows, oldest-first."""
    async with get_pool().acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT * FROM (
                SELECT * FROM pm_daily_returns ORDER BY date DESC LIMIT $1
            ) t ORDER BY date ASC
            """,
            days,
        )
        return [dict(r) for r in rows]


# ─────────────────────────────────────────────────────────────────────────────
# Portfolio snapshots
# ─────────────────────────────────────────────────────────────────────────────

async def insert_snapshot(snapshot: PortfolioSnapshot) -> None:
    positions_json = json.dumps(
        [p.model_dump(mode="json") for p in snapshot.positions]
    )
    metrics_json = json.dumps(snapshot.metrics)
    perf_json = (
        snapshot.performance_30d.model_dump(mode="json")
        if snapshot.performance_30d
        else None
    )

    async with get_pool().acquire() as conn:
        await conn.execute(
            """
            INSERT INTO pm_snapshots (
                snapshot_id, snapshot_at, initial_capital_inr, cash_balance_inr,
                equity_value_inr, total_value_inr,
                day_pnl_inr, total_pnl_inr, total_return_pct,
                gross_exposure_inr, net_exposure_inr, gross_exposure_pct,
                open_position_count, positions, performance_30d, metrics
            ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16)
            ON CONFLICT (snapshot_id) DO NOTHING
            """,
            snapshot.snapshot_id,
            snapshot.snapshot_at,
            snapshot.initial_capital_inr,
            snapshot.cash_balance_inr,
            snapshot.equity_value_inr,
            snapshot.total_value_inr,
            snapshot.day_pnl_inr,
            snapshot.total_pnl_inr,
            snapshot.total_return_pct,
            snapshot.gross_exposure_inr,
            snapshot.net_exposure_inr,
            snapshot.gross_exposure_pct,
            snapshot.open_position_count,
            positions_json,
            json.dumps(perf_json) if perf_json else None,
            metrics_json,
        )


async def get_latest_snapshot() -> dict[str, Any] | None:
    async with get_pool().acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM pm_snapshots ORDER BY snapshot_at DESC LIMIT 1"
        )
        return dict(row) if row else None


async def list_snapshots(
    *,
    since: datetime | None = None,
    limit: int = 100,
    offset: int = 0,
) -> list[dict[str, Any]]:
    clauses: list[str] = []
    values: list[Any] = []
    idx = 1

    if since:
        clauses.append(f"snapshot_at >= ${idx}")
        values.append(since)
        idx += 1

    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    query = (
        f"SELECT snapshot_id, snapshot_at, total_value_inr, total_pnl_inr, "
        f"total_return_pct, open_position_count FROM pm_snapshots {where} "
        f"ORDER BY snapshot_at DESC LIMIT ${idx} OFFSET ${idx + 1}"
    )
    values.extend([limit, offset])

    async with get_pool().acquire() as conn:
        rows = await conn.fetch(query, *values)
        return [dict(r) for r in rows]


# ─────────────────────────────────────────────────────────────────────────────
# Event idempotency guard
# ─────────────────────────────────────────────────────────────────────────────

async def claim_event(event_id: uuid.UUID) -> bool:
    """
    Claim an ExecutionEvent for processing. Returns True if newly claimed,
    False if already processed (idempotent delivery guard).
    """
    async with get_pool().acquire() as conn:
        try:
            await conn.execute(
                """
                INSERT INTO pm_processed_events (event_id, processed_at)
                VALUES ($1, now())
                """,
                event_id,
            )
            return True
        except asyncpg.UniqueViolationError:
            return False
