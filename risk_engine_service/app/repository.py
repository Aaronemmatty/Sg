from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any

import asyncpg

from app.logging_setup import get_logger
from app.models import RiskDecision

log = get_logger(module="repository")

_SCHEMA_SQL_PATH = Path(__file__).resolve().parent.parent / "sql" / "schema.sql"


class Database:
    def __init__(self, dsn: str) -> None:
        self._dsn = dsn
        self.pool: asyncpg.Pool | None = None

    async def connect(self) -> None:
        self.pool = await asyncpg.create_pool(self._dsn, min_size=2, max_size=10)
        log.info("db_pool_connected")
        await self._run_migrations()

    async def _run_migrations(self) -> None:
        """Apply this service's own schema (raw SQL, no Alembic for this
        service). Statements use CREATE TABLE IF NOT EXISTS, so re-running
        on every startup is safe and idempotent."""
        assert self.pool is not None
        if not _SCHEMA_SQL_PATH.exists():
            log.warning("schema_sql_missing", path=str(_SCHEMA_SQL_PATH))
            return
        sql = _SCHEMA_SQL_PATH.read_text()
        async with self.pool.acquire() as conn:
            await conn.execute(sql)
        log.info("schema_migrations_applied", path=str(_SCHEMA_SQL_PATH))

    async def disconnect(self) -> None:
        if self.pool:
            await self.pool.close()
            log.info("db_pool_closed")

    async def insert_risk_decision(self, decision: RiskDecision) -> None:
        assert self.pool is not None
        checks_json = json.dumps({k: v.model_dump() for k, v in decision.checks.items()})
        rejection_json = json.dumps([r.value for r in decision.rejection_reasons])
        async with self.pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO risk_decisions (
                    intent_id, correlation_id, symbol, action,
                    original_allocation_inr, approved_allocation_inr,
                    risk_score, risk_band, var_inr, var_percent_of_portfolio,
                    status, rejection_reasons, checks, kill_switch_active,
                    market_regime, evaluated_at
                ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16)
                """,
                decision.intent_id,
                decision.correlation_id,
                decision.symbol,
                decision.action,
                decision.original_allocation_inr,
                decision.approved_allocation_inr,
                decision.risk_score,
                decision.risk_band.value,
                decision.var_inr,
                decision.var_percent_of_portfolio,
                decision.status.value,
                rejection_json,
                checks_json,
                decision.kill_switch_active,
                decision.market_regime,
                decision.evaluated_at,
            )

    async def insert_audit_log(self, intent_id: uuid.UUID | None, event_type: str, detail: dict[str, Any]) -> None:
        assert self.pool is not None
        async with self.pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO risk_audit_logs (intent_id, event_type, detail) VALUES ($1,$2,$3)",
                intent_id,
                event_type,
                json.dumps(detail, default=str),
            )

    async def insert_kill_switch_event(
        self, previous_state: str, new_state: str, reason: str, triggered_by: str, actor: str, metadata: dict[str, Any]
    ) -> None:
        assert self.pool is not None
        async with self.pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO kill_switch_events (previous_state, new_state, reason, triggered_by, actor, metadata)
                VALUES ($1,$2,$3,$4,$5,$6)
                """,
                previous_state,
                new_state,
                reason,
                triggered_by,
                actor,
                json.dumps(metadata, default=str),
            )

    async def insert_circuit_breaker_event(
        self, symbol: str, state: str, reason: str, metric_value: float | None, threshold: float | None
    ) -> None:
        assert self.pool is not None
        async with self.pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO circuit_breaker_events (symbol, state, reason, metric_value, threshold)
                VALUES ($1,$2,$3,$4,$5)
                """,
                symbol,
                state,
                reason,
                metric_value,
                threshold,
            )

    async def get_policy(self, policy_name: str) -> dict[str, Any] | None:
        assert self.pool is not None
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT policy_name, enabled, params, description FROM risk_policies WHERE policy_name = $1",
                policy_name,
            )
            if row is None:
                return None
            return {
                "policy_name": row["policy_name"],
                "enabled": row["enabled"],
                "params": json.loads(row["params"]) if isinstance(row["params"], str) else row["params"],
                "description": row["description"],
            }

    async def get_all_policies(self) -> list[dict[str, Any]]:
        assert self.pool is not None
        async with self.pool.acquire() as conn:
            rows = await conn.fetch("SELECT policy_name, enabled, params, description FROM risk_policies")
            return [
                {
                    "policy_name": r["policy_name"],
                    "enabled": r["enabled"],
                    "params": json.loads(r["params"]) if isinstance(r["params"], str) else r["params"],
                    "description": r["description"],
                }
                for r in rows
            ]

    async def upsert_policy(self, policy_name: str, enabled: bool, params: dict[str, Any], updated_by: str) -> None:
        assert self.pool is not None
        async with self.pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO risk_policies (policy_name, enabled, params, updated_by, updated_at)
                VALUES ($1, $2, $3, $4, now())
                ON CONFLICT (policy_name) DO UPDATE SET
                    enabled = EXCLUDED.enabled,
                    params = EXCLUDED.params,
                    updated_by = EXCLUDED.updated_by,
                    updated_at = now()
                """,
                policy_name,
                enabled,
                json.dumps(params),
                updated_by,
            )

    async def recent_decisions(self, symbol: str | None, status: str | None, limit: int) -> list[dict[str, Any]]:
        assert self.pool is not None
        query = "SELECT * FROM risk_decisions WHERE TRUE"
        params: list[Any] = []
        if symbol:
            params.append(symbol)
            query += f" AND symbol = ${len(params)}"
        if status:
            params.append(status)
            query += f" AND status = ${len(params)}"
        params.append(limit)
        query += f" ORDER BY evaluated_at DESC LIMIT ${len(params)}"
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(query, *params)
            return [dict(r) for r in rows]
