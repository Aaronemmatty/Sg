"""FastAPI application factory — Execution Orchestrator Service."""
from __future__ import annotations

import os
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from prometheus_fastapi_instrumentator import Instrumentator

from app.api.v1.router import api_router
from app.core.config import get_settings
from app.core.logging import configure_logging, get_logger
from app.core.redis import close_redis, get_redis
from app.core.tracing import configure_tracing
from app.db.session import close_db
from app.middleware.correlation import CorrelationIdMiddleware

settings = get_settings()
log = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    configure_logging()
    configure_tracing()

    # Warm up Redis
    await get_redis()

    # Shared mutable regime cache — updated by regime consumer, read by pipeline
    regime_cache: dict[str, str] = {}

    # Instantiate services
    from app.services.orchestrator_service import OrchestratorService
    from app.consumers.signal_consumer import SignalConsumer
    from app.utils.app_state import set_consumer, set_orchestrator_service

    svc = OrchestratorService(regime_cache=regime_cache)
    set_orchestrator_service(svc)

    consumer = SignalConsumer(orchestrator=svc, regime_cache=regime_cache)
    set_consumer(consumer)
    consumer.start()

    log.info(
        "execution_orchestrator_started",
        version=settings.APP_VERSION,
        env=settings.APP_ENV,
        port=settings.PORT,
    )

    yield

    # Shutdown
    await consumer.stop()
    await close_redis()
    await close_db()
    log.info("execution_orchestrator_stopped")


def create_app() -> FastAPI:
    app = FastAPI(
        title="SG Execution Orchestrator",
        description=(
            "Transforms aggregated signals into executable trade intents. "
            "Does NOT place orders — downstream Execution Engine handles that."
        ),
        version=settings.APP_VERSION,
        docs_url="/docs" if settings.APP_ENV != "production" else None,
        redoc_url=None,
        openapi_url="/openapi.json" if settings.APP_ENV != "production" else None,
        lifespan=lifespan,
    )

    app.add_middleware(CorrelationIdMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[os.getenv("ALLOWED_ORIGINS", "http://localhost")],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(api_router)

    @app.exception_handler(Exception)
    async def unhandled(_request: Request, exc: Exception) -> JSONResponse:
        log.error(
            "unhandled_exception",
            path=_request.url.path,
            error=str(exc),
            exc_info=True,
        )
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"detail": "Internal server error"},
        )

    if settings.PROMETHEUS_ENABLED:
        Instrumentator().instrument(app).expose(
            app, endpoint="/metrics", include_in_schema=False
        )

    return app


app = create_app()
