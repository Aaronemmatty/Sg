from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from prometheus_fastapi_instrumentator import Instrumentator

from app.api.v1.router import api_router
from app.core.config import settings
from app.core.logging import log
from app.core.redis import close_redis
from app.core.tracing import configure_tracing
from app.db.session import close_pool, init_pool, run_migrations
from app.services.job_manager import JobManager


@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info("service_starting", service=settings.service_name, port=settings.port)

    pool = await init_pool()
    app.state.db_pool = pool
    await run_migrations()

    app.state.job_manager = JobManager(pool)

    configure_tracing(app)

    log.info("service_started")
    try:
        yield
    finally:
        log.info("service_stopping")
        await close_redis()
        await close_pool()
        log.info("service_stopped")


app = FastAPI(
    title="Backtesting Engine Service",
    description=(
        "Institutional-grade strategy backtesting: historical replay, "
        "multi-timeframe support, transaction costs & slippage modelling, "
        "walk-forward analysis, and Monte Carlo robustness testing."
    ),
    version="0.1.0",
    lifespan=lifespan,
)

Instrumentator().instrument(app).expose(app, endpoint="/metrics", include_in_schema=False)

app.include_router(api_router)


@app.get("/", include_in_schema=False)
async def root() -> dict:
    return {"service": settings.service_name, "status": "running"}
