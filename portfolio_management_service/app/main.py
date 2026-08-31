"""
portfolio_management_service (8009) — FastAPI application.

Lifespan responsibilities:
  - Open DB pool, run migrations
  - Connect Redis
  - Start background tasks:
      · ExecutionConsumer — subscribes sg:executions:* and processes fills
      · MTM refresh loop  — refreshes all position prices on a timer
      · Snapshot loop     — persists portfolio snapshots periodically
  - Graceful shutdown of all of the above

Architecture note:
  - 8009 is the canonical source of truth for portfolio/position state.
  - risk_engine_service (8007) should call GET /api/v1/portfolio/snapshot here,
    NOT broker_service (8003). The risk_engine client needs to be repointed.
"""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI
from prometheus_fastapi_instrumentator import Instrumentator

from app.api.v1.router import api_router
from app.consumers.execution_consumer import ExecutionConsumer
from app.core.config import settings
from app.core.logging import configure_logging, get_logger
from app.core.redis import close_redis, get_redis
from app.core.tracing import configure_tracing
from app.db.session import close_pool, init_pool
from app.publishers import portfolio_publisher
from app.services.market_data_client import market_data_client
from app.services.mtm_service import refresh_all_positions
from app.services.snapshot_service import build_and_persist

configure_logging()
log = get_logger(__name__)

_stop_event = asyncio.Event()
_background_tasks: list[asyncio.Task] = []


# ─────────────────────────────────────────────────────────────────────────────
# Background task coroutines
# ─────────────────────────────────────────────────────────────────────────────

async def _mtm_refresh_loop() -> None:
    """Refresh mark-to-market prices for all open positions on a timer."""
    log.info("mtm_refresh_loop_started", interval_s=settings.mtm_refresh_interval_seconds)
    while not _stop_event.is_set():
        try:
            updated = await refresh_all_positions()
            if updated:
                log.debug("mtm_refreshed", positions=len(updated))
        except Exception:
            log.exception("mtm_refresh_loop_error")
        try:
            await asyncio.wait_for(
                _stop_event.wait(), timeout=settings.mtm_refresh_interval_seconds
            )
        except asyncio.TimeoutError:
            pass
    log.info("mtm_refresh_loop_stopped")


async def _snapshot_loop() -> None:
    """Persist portfolio snapshots at a configured interval."""
    log.info("snapshot_loop_started", interval_s=settings.snapshot_interval_seconds)
    while not _stop_event.is_set():
        try:
            snapshot = await build_and_persist(refresh_mtm=False)  # MTM loop already refreshed
            log.info(
                "snapshot_persisted_background",
                snapshot_id=str(snapshot.snapshot_id),
                total_value=float(snapshot.total_value_inr),
            )
        except Exception:
            log.exception("snapshot_loop_error")
        try:
            await asyncio.wait_for(
                _stop_event.wait(), timeout=settings.snapshot_interval_seconds
            )
        except asyncio.TimeoutError:
            pass
    log.info("snapshot_loop_stopped")


# ─────────────────────────────────────────────────────────────────────────────
# Application lifespan
# ─────────────────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info("portfolio_management_starting", env=settings.env, port=settings.service_port)

    await init_pool()
    redis_client = await get_redis()
    portfolio_publisher.set_redis_client(redis_client)

    consumer = ExecutionConsumer(redis_client)

    consumer_task = asyncio.create_task(consumer.run(_stop_event))
    mtm_task = asyncio.create_task(_mtm_refresh_loop())
    snapshot_task = asyncio.create_task(_snapshot_loop())
    _background_tasks.extend([consumer_task, mtm_task, snapshot_task])

    log.info("portfolio_management_started")
    try:
        yield
    finally:
        log.info("portfolio_management_stopping")
        _stop_event.set()
        await consumer.shutdown()
        for task in _background_tasks:
            task.cancel()
        await asyncio.gather(*_background_tasks, return_exceptions=True)
        await market_data_client.aclose()
        await close_redis()
        await close_pool()
        log.info("portfolio_management_stopped")


# ─────────────────────────────────────────────────────────────────────────────
# FastAPI app
# ─────────────────────────────────────────────────────────────────────────────

app = FastAPI(
    title="portfolio_management_service",
    version="0.1.0",
    description="Portfolio Management Service (8009) — SG Trading Platform",
    lifespan=lifespan,
)

app.include_router(api_router)


@app.get("/health", include_in_schema=False)
async def root_health():
    from app.api.v1.endpoints.health import health
    return await health()

Instrumentator().instrument(app).expose(app, endpoint="/metrics")

try:
    configure_tracing(app)
except Exception:
    log.warning("otel_tracing_setup_failed_continuing_without_tracing")
