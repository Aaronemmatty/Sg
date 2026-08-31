"""
Persistence layer (asyncpg) for execution_engine_service.

A single module-level pool (`db.pool`) is created at app startup (see
app/main.py lifespan) and reused everywhere. All functions take an
optional `conn` so callers can compose multi-statement transactions when
needed (e.g. insert order + audit log atomically).
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import asyncpg

from app.config import settings
from app.logging_config import get_logger
from app.models import Execution, Order, OrderState

log = get_logger(__name__)

pool: asyncpg.Pool | None = None


async def init_pool() -> asyncpg.Pool:
    global pool
    pool = await asyncpg.create_pool(
        dsn=settings.database_url,
        min_size=settings.db_pool_min_size,
        max_size=settings.db_pool_max_size,
    )
    await _run_migrations(pool)
    log.info("db_pool_initialized", min_size=settings.db_pool_min_size, max_size=settings.db_pool_max_size)
    return pool


async def close_pool() -> None:
    global pool
    if pool is not None:
        await pool.close()
        pool = None
        log.info("db_pool_closed")


async def _run_migrations(p: asyncpg.Pool) -> None:
    migrations_dir = Path(__file__).resolve().parent.parent / "migrations"
    for migration_file in sorted(migrations_dir.glob("*.sql")):
        sql = migration_file.read_text()
        async with p.acquire() as conn:
            await conn.execute(sql)
        log.info("migration_applied", file=migration_file.name)


def _row_to_order(row: asyncpg.Record) -> Order:
    return Order(
        order_id=row["order_id"],
        intent_id=row["intent_id"],
        correlation_id=row["correlation_id"],
        symbol=row["symbol"],
        action=row["action"],
        state=row["state"],
        approved_allocation_inr=float(row["approved_allocation_inr"]),
        quantity=row["quantity"],
        order_type=row["order_type"],
        limit_price=float(row["limit_price"]) if row["limit_price"] is not None else None,
        validity=row["validity"],
        execution_style=row["execution_style"],
        risk_band=row["risk_band"],
        market_regime=row["market_regime"],
        broker_order_id=row["broker_order_id"],
        idempotency_key=row["idempotency_key"],
        intended_price_inr=float(row["intended_price_inr"]) if row["intended_price_inr"] is not None else None,
        avg_fill_price_inr=float(row["avg_fill_price_inr"]) if row["avg_fill_price_inr"] is not None else None,
        filled_quantity=row["filled_quantity"],
        retry_count=row["retry_count"],
        last_error=row["last_error"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        held_until=row["held_until"],
    )


# --------------------------------------------------------------------------
# Idempotency
# --------------------------------------------------------------------------

async def claim_idempotency_key(key: str, order_id: uuid.UUID) -> bool:
    """Atomically claim an idempotency key. Returns False if it already exists
    (i.e. this intent/retry was already processed) and True if newly claimed."""
    expires_at = datetime.now(timezone.utc) + timedelta(seconds=settings.idempotency_key_ttl_seconds)
    async with pool.acquire() as conn:
        try:
            await conn.execute(
                """INSERT INTO idempotency_keys (idempotency_key, order_id, expires_at)
                   VALUES ($1, $2, $3)""",
                key, order_id, expires_at,
            )
            return True
        except asyncpg.UniqueViolationError:
            return False


async def get_order_id_for_idempotency_key(key: str) -> uuid.UUID | None:
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT order_id FROM idempotency_keys WHERE idempotency_key = $1", key)
        return row["order_id"] if row else None


# --------------------------------------------------------------------------
# exec_orders
# --------------------------------------------------------------------------

async def insert_order(order: Order, actor: str = "system", reason: str = "intent_received") -> None:
    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute(
                """
                INSERT INTO exec_orders (
                    order_id, intent_id, correlation_id, symbol, action, state,
                    approved_allocation_inr, quantity, order_type, limit_price, validity,
                    execution_style, risk_band, market_regime, broker_order_id,
                    idempotency_key, intended_price_inr, avg_fill_price_inr,
                    filled_quantity, retry_count, last_error, created_at, updated_at, held_until
                ) VALUES (
                    $1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17,$18,$19,$20,$21,$22,$23,$24
                )
                """,
                order.order_id, order.intent_id, order.correlation_id, order.symbol, order.action.value,
                order.state.value, order.approved_allocation_inr, order.quantity,
                order.order_type.value if order.order_type else None, order.limit_price,
                order.validity.value, order.execution_style.value, order.risk_band, order.market_regime,
                order.broker_order_id, order.idempotency_key, order.intended_price_inr,
                order.avg_fill_price_inr, order.filled_quantity, order.retry_count, order.last_error,
                order.created_at, order.updated_at, order.held_until,
            )
            await _insert_audit_log(conn, order.order_id, order.intent_id, None, order.state, actor, reason, None)


async def update_order_state(
    order_id: uuid.UUID,
    from_state: OrderState,
    to_state: OrderState,
    *,
    actor: str = "system",
    reason: str | None = None,
    detail: dict[str, Any] | None = None,
    **fields: Any,
) -> Order:
    """Update order state + arbitrary fields, write audit log, return refreshed Order.
    Optimistic concurrency: WHERE state = from_state guards against racing updates
    (e.g. reconciliation loop and post-submit poller updating the same order)."""
    set_clauses = ["state = $1", "updated_at = now()"]
    values: list[Any] = [to_state.value]
    idx = 2
    for field_name, value in fields.items():
        set_clauses.append(f"{field_name} = ${idx}")
        values.append(value)
        idx += 1

    query = f"""
        UPDATE exec_orders SET {', '.join(set_clauses)}
        WHERE order_id = ${idx} AND state = ${idx + 1}
        RETURNING *
    """
    values.extend([order_id, from_state.value])

    async with pool.acquire() as conn:
        async with conn.transaction():
            row = await conn.fetchrow(query, *values)
            if row is None:
                raise StaleOrderStateError(order_id, from_state, to_state)
            order = _row_to_order(row)
            await _insert_audit_log(conn, order_id, order.intent_id, from_state, to_state, actor, reason, detail)
            return order


class StaleOrderStateError(Exception):
    def __init__(self, order_id: uuid.UUID, expected_from: OrderState, target: OrderState):
        super().__init__(
            f"Order {order_id} was not in expected state {expected_from} when transitioning to {target} "
            f"(concurrent update detected)"
        )


async def get_order(order_id: uuid.UUID) -> Order | None:
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM exec_orders WHERE order_id = $1", order_id)
        return _row_to_order(row) if row else None


async def get_order_by_broker_order_id(broker_order_id: str) -> Order | None:
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM exec_orders WHERE broker_order_id = $1", broker_order_id)
        return _row_to_order(row) if row else None


async def list_orders(
    *, symbol: str | None = None, state: OrderState | None = None, limit: int = 100, offset: int = 0
) -> list[Order]:
    clauses, values = [], []
    idx = 1
    if symbol:
        clauses.append(f"symbol = ${idx}")
        values.append(symbol.upper())
        idx += 1
    if state:
        clauses.append(f"state = ${idx}")
        values.append(state.value)
        idx += 1
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    query = f"SELECT * FROM exec_orders {where} ORDER BY created_at DESC LIMIT ${idx} OFFSET ${idx + 1}"
    values.extend([limit, offset])
    async with pool.acquire() as conn:
        rows = await conn.fetch(query, *values)
        return [_row_to_order(r) for r in rows]


async def list_non_terminal_orders() -> list[Order]:
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """SELECT * FROM exec_orders
               WHERE state IN ('SUBMITTED', 'ACKNOWLEDGED', 'PARTIALLY_FILLED')"""
        )
        return [_row_to_order(r) for r in rows]


# --------------------------------------------------------------------------
# Executions (fills)
# --------------------------------------------------------------------------

async def insert_execution(execution: Execution) -> None:
    async with pool.acquire() as conn:
        await conn.execute(
            """INSERT INTO executions (
                   execution_id, order_id, broker_execution_id, fill_quantity,
                   fill_price_inr, fill_timestamp, slippage_inr, slippage_bps
               ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8)""",
            execution.execution_id, execution.order_id, execution.broker_execution_id,
            execution.fill_quantity, execution.fill_price_inr, execution.fill_timestamp,
            execution.slippage_inr, execution.slippage_bps,
        )


async def list_executions_for_order(order_id: uuid.UUID) -> list[Execution]:
    async with pool.acquire() as conn:
        rows = await conn.fetch("SELECT * FROM executions WHERE order_id = $1 ORDER BY fill_timestamp", order_id)
        return [
            Execution(
                execution_id=r["execution_id"], order_id=r["order_id"],
                broker_execution_id=r["broker_execution_id"], fill_quantity=r["fill_quantity"],
                fill_price_inr=float(r["fill_price_inr"]), fill_timestamp=r["fill_timestamp"],
                slippage_inr=float(r["slippage_inr"]) if r["slippage_inr"] is not None else None,
                slippage_bps=float(r["slippage_bps"]) if r["slippage_bps"] is not None else None,
            )
            for r in rows
        ]


# --------------------------------------------------------------------------
# Audit log
# --------------------------------------------------------------------------

async def _insert_audit_log(
    conn: asyncpg.Connection,
    order_id: uuid.UUID,
    intent_id: uuid.UUID | None,
    from_state: OrderState | None,
    to_state: OrderState,
    actor: str,
    reason: str | None,
    detail: dict[str, Any] | None,
) -> None:
    await conn.execute(
        """INSERT INTO execution_audit_logs (order_id, intent_id, from_state, to_state, actor, reason, detail)
           VALUES ($1,$2,$3,$4,$5,$6,$7)""",
        order_id, intent_id, from_state.value if from_state else None, to_state.value,
        actor, reason, json.dumps(detail) if detail is not None else None,
    )


async def list_audit_logs_for_order(order_id: uuid.UUID) -> list[dict[str, Any]]:
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT * FROM execution_audit_logs WHERE order_id = $1 ORDER BY created_at", order_id
        )
        return [dict(r) for r in rows]


# --------------------------------------------------------------------------
# Held intents (RISK_HOLD parking)
# --------------------------------------------------------------------------

async def insert_held_intent(intent_id: uuid.UUID, order_id: uuid.UUID, symbol: str, raw_payload: dict[str, Any]) -> None:
    expires_at = datetime.now(timezone.utc) + timedelta(seconds=settings.hold_max_age_seconds)
    async with pool.acquire() as conn:
        await conn.execute(
            """INSERT INTO held_intents (intent_id, order_id, symbol, raw_payload, expires_at)
               VALUES ($1,$2,$3,$4,$5)
               ON CONFLICT (intent_id) DO NOTHING""",
            intent_id, order_id, symbol.upper(), json.dumps(raw_payload), expires_at,
        )


async def list_expired_held_intents() -> list[dict[str, Any]]:
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT * FROM held_intents WHERE NOT resolved AND expires_at <= now()"
        )
        return [dict(r) for r in rows]


async def mark_held_intent_resolved(intent_id: uuid.UUID) -> None:
    async with pool.acquire() as conn:
        await conn.execute("UPDATE held_intents SET resolved = TRUE WHERE intent_id = $1", intent_id)
