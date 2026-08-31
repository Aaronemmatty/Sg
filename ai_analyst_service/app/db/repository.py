from __future__ import annotations

import uuid

import asyncpg

from app.models.domain import AnalysisCapability, AuditLogEntry, PromptTemplate


class AnalystRepository:
    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    # ── Prompt templates ─────────────────────────────────────────────────────

    async def get_active_template(self, capability: AnalysisCapability) -> PromptTemplate | None:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM ai_prompt_templates WHERE capability = $1 AND is_active = true",
                capability.value,
            )
        return self._row_to_template(row) if row else None

    async def list_templates(self, capability: AnalysisCapability | None = None) -> list[PromptTemplate]:
        async with self._pool.acquire() as conn:
            if capability:
                rows = await conn.fetch(
                    "SELECT * FROM ai_prompt_templates WHERE capability = $1 ORDER BY version DESC",
                    capability.value,
                )
            else:
                rows = await conn.fetch(
                    "SELECT * FROM ai_prompt_templates ORDER BY capability, version DESC"
                )
        return [self._row_to_template(r) for r in rows]

    async def create_template(
        self,
        capability: AnalysisCapability,
        system_prompt: str,
        user_template: str,
        created_by: str | None,
        activate: bool = False,
    ) -> PromptTemplate:
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                next_version_row = await conn.fetchrow(
                    "SELECT COALESCE(MAX(version), 0) + 1 AS next_version "
                    "FROM ai_prompt_templates WHERE capability = $1",
                    capability.value,
                )
                next_version = next_version_row["next_version"]
                template_id = uuid.uuid4()

                if activate:
                    await conn.execute(
                        "UPDATE ai_prompt_templates SET is_active = false WHERE capability = $1",
                        capability.value,
                    )

                row = await conn.fetchrow(
                    """
                    INSERT INTO ai_prompt_templates
                        (id, capability, version, system_prompt, user_template, is_active, created_by)
                    VALUES ($1, $2, $3, $4, $5, $6, $7)
                    RETURNING *
                    """,
                    template_id,
                    capability.value,
                    next_version,
                    system_prompt,
                    user_template,
                    activate,
                    created_by,
                )
        return self._row_to_template(row)

    async def activate_template(self, capability: AnalysisCapability, version: int) -> PromptTemplate | None:
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                await conn.execute(
                    "UPDATE ai_prompt_templates SET is_active = false WHERE capability = $1",
                    capability.value,
                )
                row = await conn.fetchrow(
                    """
                    UPDATE ai_prompt_templates SET is_active = true
                    WHERE capability = $1 AND version = $2
                    RETURNING *
                    """,
                    capability.value,
                    version,
                )
        return self._row_to_template(row) if row else None

    @staticmethod
    def _row_to_template(row: asyncpg.Record) -> PromptTemplate:
        return PromptTemplate(
            id=row["id"],
            capability=AnalysisCapability(row["capability"]),
            version=row["version"],
            system_prompt=row["system_prompt"],
            user_template=row["user_template"],
            is_active=row["is_active"],
            created_at=row["created_at"],
            created_by=row["created_by"],
        )

    # ── Audit log ─────────────────────────────────────────────────────────────

    async def write_audit_entry(self, entry: AuditLogEntry) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO ai_audit_log
                    (id, user_sub, capability, cache_hit, status, latency_ms,
                     input_tokens, output_tokens, error, created_at)
                VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10)
                """,
                entry.id,
                entry.user_sub,
                entry.capability.value,
                entry.cache_hit,
                entry.status,
                entry.latency_ms,
                entry.input_tokens,
                entry.output_tokens,
                entry.error,
                entry.created_at,
            )

    async def get_audit_summary(self, hours: int = 24) -> dict:
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT capability, status, count(*) AS n,
                       COALESCE(sum(input_tokens), 0) AS input_tokens,
                       COALESCE(sum(output_tokens), 0) AS output_tokens,
                       COALESCE(avg(latency_ms), 0) AS avg_latency_ms
                FROM ai_audit_log
                WHERE created_at >= now() - ($1 || ' hours')::interval
                GROUP BY capability, status
                ORDER BY capability, status
                """,
                str(hours),
            )
        return {
            "window_hours": hours,
            "breakdown": [dict(r) for r in rows],
        }
