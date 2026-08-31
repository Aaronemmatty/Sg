"""
Repository — all asyncpg queries for ml_platform_service.

Tables: ml_training_jobs, ml_model_versions, ml_predictions,
        ml_prediction_outcomes, ml_drift_reports, ml_feature_snapshots,
        ml_experiment_runs
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime
from typing import Any

import asyncpg

from app.db.session import pool
from app.models.domain import (
    ModelPrediction,
    ModelStatus,
    ModelType,
    ModelVersion,
    DriftReport,
    PredictionOutcome,
    TrainingJob,
    TrainingStatus,
)
from app.core.metrics import champion_models_active, model_promotions_total


# ── Training jobs ─────────────────────────────────────────────────────────────

async def upsert_training_job(job: TrainingJob) -> None:
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO ml_training_jobs (
                job_id, model_type, symbol, target_type, status,
                n_samples, train_metric, val_metric, test_metric,
                best_params, mlflow_run_id, model_version_id,
                error_message, started_at, completed_at, duration_seconds, created_at
            ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17)
            ON CONFLICT (job_id) DO UPDATE SET
                status          = EXCLUDED.status,
                n_samples       = EXCLUDED.n_samples,
                train_metric    = EXCLUDED.train_metric,
                val_metric      = EXCLUDED.val_metric,
                test_metric     = EXCLUDED.test_metric,
                best_params     = EXCLUDED.best_params,
                mlflow_run_id   = EXCLUDED.mlflow_run_id,
                model_version_id = EXCLUDED.model_version_id,
                error_message   = EXCLUDED.error_message,
                started_at      = EXCLUDED.started_at,
                completed_at    = EXCLUDED.completed_at,
                duration_seconds = EXCLUDED.duration_seconds
            """,
            job.job_id, job.model_type.value, job.symbol, job.target_type.value,
            job.status.value, job.n_samples, job.train_metric, job.val_metric,
            job.test_metric, json.dumps(job.best_params), job.mlflow_run_id,
            job.model_version_id, job.error_message, job.started_at,
            job.completed_at, job.duration_seconds, job.created_at,
        )


async def get_training_job(job_id: uuid.UUID) -> dict[str, Any] | None:
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM ml_training_jobs WHERE job_id = $1", job_id
        )
        return dict(row) if row else None


async def list_training_jobs(
    symbol: str | None = None,
    model_type: str | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    clauses, vals, i = [], [], 1
    if symbol:
        clauses.append(f"symbol = ${i}"); vals.append(symbol); i += 1
    if model_type:
        clauses.append(f"model_type = ${i}"); vals.append(model_type); i += 1
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            f"SELECT * FROM ml_training_jobs {where} ORDER BY created_at DESC LIMIT ${i}",
            *vals, limit,
        )
        return [dict(r) for r in rows]


# ── Model registry ────────────────────────────────────────────────────────────

async def register_model_version(version: ModelVersion) -> ModelVersion:
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO ml_model_versions (
                version_id, model_type, symbol, target_type, status,
                artifact_path, mlflow_run_id, train_metric, val_metric,
                test_metric, directional_accuracy, sharpe_on_signals,
                hyperparams, feature_count, n_samples, training_job_id, created_at
            ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17)
            """,
            version.version_id, version.model_type.value, version.symbol,
            version.target_type.value, version.status.value, version.artifact_path,
            version.mlflow_run_id, version.train_metric, version.val_metric,
            version.test_metric, version.directional_accuracy, version.sharpe_on_signals,
            json.dumps(version.hyperparams), version.feature_count, version.n_samples,
            version.training_job_id, version.created_at,
        )
    return version


async def get_champion_model(symbol: str, model_type: ModelType) -> ModelVersion | None:
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT * FROM ml_model_versions
            WHERE symbol = $1 AND model_type = $2 AND status = 'champion'
            ORDER BY created_at DESC LIMIT 1
            """,
            symbol, model_type.value,
        )
        if row is None:
            return None
        return _row_to_version(row)


async def list_model_versions(
    symbol: str | None = None,
    model_type: str | None = None,
    status: str | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    clauses, vals, i = [], [], 1
    for col, val in [("symbol", symbol), ("model_type", model_type), ("status", status)]:
        if val:
            clauses.append(f"{col} = ${i}"); vals.append(val); i += 1
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            f"SELECT * FROM ml_model_versions {where} ORDER BY created_at DESC LIMIT ${i}",
            *vals, limit,
        )
        return [dict(r) for r in rows]


async def promote_model(version_id: uuid.UUID) -> None:
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT model_type, symbol FROM ml_model_versions WHERE version_id = $1", version_id
        )
        if row is None:
            return
        await conn.execute(
            """
            UPDATE ml_model_versions SET
                status = 'champion', promoted_at = now()
            WHERE version_id = $1
            """,
            version_id,
        )
    # Evict from serving cache
    from app.serving.predictor import invalidate_model_cache
    invalidate_model_cache(row["symbol"], ModelType(row["model_type"]))
    model_promotions_total.labels(model_type=row["model_type"]).inc()
    # Refresh gauge
    await _refresh_champion_count()


async def retire_model(version_id: uuid.UUID) -> None:
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE ml_model_versions SET status='retired', retired_at=now() WHERE version_id=$1",
            version_id,
        )


async def _refresh_champion_count() -> None:
    async with pool.acquire() as conn:
        n = await conn.fetchval(
            "SELECT COUNT(*) FROM ml_model_versions WHERE status='champion'"
        )
        champion_models_active.set(n or 0)


def _row_to_version(row: asyncpg.Record) -> ModelVersion:
    d = dict(row)
    d["hyperparams"] = json.loads(d.get("hyperparams") or "{}")
    d["model_type"] = ModelType(d["model_type"])
    d["status"] = ModelStatus(d["status"])
    from app.models.domain import TargetType
    d["target_type"] = TargetType(d["target_type"])
    return ModelVersion(**{k: v for k, v in d.items() if k in ModelVersion.model_fields})


# ── Predictions ───────────────────────────────────────────────────────────────

async def insert_prediction(pred: ModelPrediction) -> None:
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO ml_predictions (
                prediction_id, model_version_id, model_type, symbol,
                timestamp, direction, confidence, raw_probabilities,
                predicted_return, latency_ms, created_at
            ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11)
            ON CONFLICT (prediction_id) DO NOTHING
            """,
            pred.prediction_id, pred.model_version_id, pred.model_type.value,
            pred.symbol, pred.timestamp, pred.direction.value, pred.confidence,
            json.dumps(pred.raw_probabilities), pred.predicted_return,
            pred.latency_ms, pred.created_at,
        )


async def get_prediction(prediction_id: uuid.UUID) -> ModelPrediction | None:
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM ml_predictions WHERE prediction_id = $1", prediction_id
        )
        if row is None:
            return None
        d = dict(row)
        d["raw_probabilities"] = json.loads(d.get("raw_probabilities") or "{}")
        d["model_type"] = ModelType(d["model_type"])
        d["direction"] = __import__("app.models.domain", fromlist=["SignalDirection"]).SignalDirection(d["direction"])
        return ModelPrediction(**{k: v for k, v in d.items() if k in ModelPrediction.model_fields})


async def list_predictions(
    symbol: str | None = None,
    model_type: str | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    clauses, vals, i = [], [], 1
    for col, val in [("symbol", symbol), ("model_type", model_type)]:
        if val:
            clauses.append(f"{col} = ${i}"); vals.append(val); i += 1
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            f"SELECT * FROM ml_predictions {where} ORDER BY created_at DESC LIMIT ${i}",
            *vals, limit,
        )
        return [dict(r) for r in rows]


# ── Prediction outcomes ───────────────────────────────────────────────────────

async def insert_prediction_outcome(outcome: PredictionOutcome) -> None:
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO ml_prediction_outcomes (
                outcome_id, prediction_id, symbol, model_type,
                predicted_direction, actual_direction, actual_return,
                correct, outcome_at, recorded_at
            ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10)
            ON CONFLICT (outcome_id) DO NOTHING
            """,
            outcome.outcome_id, outcome.prediction_id, outcome.symbol,
            outcome.model_type.value,
            outcome.predicted_direction.value,
            outcome.actual_direction.value if outcome.actual_direction else None,
            outcome.actual_return, outcome.correct,
            outcome.outcome_at, outcome.recorded_at,
        )


async def get_recent_outcomes(
    symbol: str, model_type: ModelType, limit: int = 50
) -> list[dict[str, Any]]:
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT * FROM ml_prediction_outcomes
            WHERE symbol = $1 AND model_type = $2
            ORDER BY outcome_at DESC LIMIT $3
            """,
            symbol, model_type.value, limit,
        )
        return [dict(r) for r in rows]


# ── Drift reports ─────────────────────────────────────────────────────────────

async def insert_drift_report(report: DriftReport) -> None:
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO ml_drift_reports (
                report_id, symbol, model_version_id, feature_psi,
                overall_psi, drift_detected, n_reference_samples,
                n_current_samples, computed_at
            ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9)
            """,
            report.report_id, report.symbol, report.model_version_id,
            json.dumps(report.feature_psi), report.overall_psi,
            report.drift_detected, report.n_reference_samples,
            report.n_current_samples, report.computed_at,
        )


async def get_latest_drift_report(
    symbol: str, model_type_value: str
) -> dict[str, Any] | None:
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT dr.* FROM ml_drift_reports dr
            JOIN ml_model_versions mv ON mv.version_id = dr.model_version_id
            WHERE dr.symbol = $1 AND mv.model_type = $2
            ORDER BY dr.computed_at DESC LIMIT 1
            """,
            symbol, model_type_value,
        )
        return dict(row) if row else None
