"""
ml_platform_service (8011) — FastAPI application.

Background tasks started in lifespan:
  - CandleConsumer: subscribes sg:market:candle:*, drives feature+prediction pipeline
  - Scheduled retraining loop: daily after-market retrain of all champion models
  - Drift monitoring loop: periodic PSI computation for active champions
  - Daily return recorder: records portfolio NAV daily for performance metrics

Signal pipeline:
  sg:market:candle:* → CandleConsumer → FeatureEngineer → EnsemblePrediction
    → sg:ml:signals:{symbol}   (consumed by strategy_service / orchestrator)
    → sg:ml:regime:{symbol}    (consumed by regime_detection_service / 8005)
"""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from prometheus_fastapi_instrumentator import Instrumentator

from app.api.v1.router import api_router
from app.consumers.candle_consumer import CandleConsumer
from app.core.config import settings
from app.core.logging import configure_logging, get_logger
from app.core.redis import close_redis, get_redis
from app.core.tracing import configure_tracing
from app.db.session import close_pool, init_pool
from app.services.market_data_client import market_data_client

configure_logging()
log = get_logger(__name__)

_stop_event = asyncio.Event()
_background_tasks: list[asyncio.Task] = []


# ─────────────────────────────────────────────────────────────────────────────
# Background loops
# ─────────────────────────────────────────────────────────────────────────────

async def _retraining_loop() -> None:
    """
    Daily retraining loop. After market hours (18:00 IST), retrain all
    champion models. Interval = 24h for production; 1h for dev.
    """
    interval = 3600 if settings.env == "development" else 86400
    log.info("retraining_loop_started", interval_s=interval)
    while not _stop_event.is_set():
        try:
            await asyncio.wait_for(_stop_event.wait(), timeout=interval)
        except asyncio.TimeoutError:
            pass
        if _stop_event.is_set():
            break
        try:
            from app.db import repository as repo
            from app.models.domain import ModelType, TargetType, TrainingConfig
            from app.training.dispatcher import TrainingDispatcher

            champions = await repo.list_model_versions(status="champion", limit=200)
            for v in champions:
                config = TrainingConfig(
                    model_type=ModelType(v["model_type"]),
                    symbol=v["symbol"],
                    target_type=TargetType.DIRECTION,
                    n_trials=15,
                )
                await TrainingDispatcher.submit(config)
            log.info("scheduled_retraining_submitted", n=len(champions))
        except Exception:
            log.exception("retraining_loop_error")

    log.info("retraining_loop_stopped")


async def _drift_monitoring_loop() -> None:
    """Periodic drift PSI computation for all active champion models."""
    interval = 1800  # 30 minutes
    log.info("drift_monitoring_loop_started", interval_s=interval)
    while not _stop_event.is_set():
        try:
            await asyncio.wait_for(_stop_event.wait(), timeout=interval)
        except asyncio.TimeoutError:
            pass
        if _stop_event.is_set():
            break
        try:
            from app.db import repository as repo
            from app.features.store import get_training_dataset
            from app.models.domain import ModelType
            from app.monitoring.drift_monitor import compute_drift_report

            champions = await repo.list_model_versions(status="champion", limit=200)
            for v in champions:
                try:
                    feat_df = await get_training_dataset(v["symbol"], limit=200)
                    if feat_df.empty:
                        continue
                    current_dist = {
                        col: feat_df[col].dropna().tolist()
                        for col in feat_df.columns
                        if col not in ("open", "high", "low", "close", "volume")
                    }
                    await compute_drift_report(
                        v["symbol"], ModelType(v["model_type"]), current_dist
                    )
                except Exception:
                    log.warning("drift_compute_failed_single", symbol=v["symbol"])
        except Exception:
            log.exception("drift_monitoring_loop_error")

    log.info("drift_monitoring_loop_stopped")


# ─────────────────────────────────────────────────────────────────────────────
# Lifespan
# ─────────────────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info("ml_platform_starting", env=settings.env, port=settings.service_port)

    # Ensure artifact directory exists
    Path(settings.model_artifacts_path).mkdir(parents=True, exist_ok=True)

    await init_pool()
    redis_client = await get_redis()

    consumer = CandleConsumer(redis_client, market_data_client)

    consumer_task = asyncio.create_task(consumer.run(_stop_event))
    retrain_task = asyncio.create_task(_retraining_loop())
    drift_task = asyncio.create_task(_drift_monitoring_loop())
    _background_tasks.extend([consumer_task, retrain_task, drift_task])

    log.info("ml_platform_started")
    try:
        yield
    finally:
        log.info("ml_platform_stopping")
        _stop_event.set()
        await consumer.shutdown()
        for task in _background_tasks:
            task.cancel()
        await asyncio.gather(*_background_tasks, return_exceptions=True)
        await market_data_client.aclose()
        await close_redis()
        await close_pool()
        log.info("ml_platform_stopped")


# ─────────────────────────────────────────────────────────────────────────────
# FastAPI app
# ─────────────────────────────────────────────────────────────────────────────

app = FastAPI(
    title="ml_platform_service",
    version="0.1.0",
    description="ML Platform Service (8011) — SG Trading Platform",
    lifespan=lifespan,
)

app.include_router(api_router)

@app.get("/health", include_in_schema=False)
async def health_check():
    return {"status": "ok", "service": "ml_platform_service"}

Instrumentator().instrument(app).expose(app, endpoint="/metrics")

try:
    configure_tracing(app)
except Exception:
    log.warning("otel_tracing_setup_failed")
