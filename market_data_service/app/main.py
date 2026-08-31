"""FastAPI application factory — Market Data Service."""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from collections.abc import AsyncGenerator

from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from prometheus_fastapi_instrumentator import Instrumentator

from app.api.v1.router import api_router
from app.core.config import get_settings
from app.core.logging import configure_logging, get_logger
from app.core.redis import close_redis, get_redis
from app.db.session import AsyncSessionLocal, engine
from app.services.engine import get_engine, init_engine

settings = get_settings()
log = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    configure_logging()

    # Warm up Redis
    await get_redis()

    # Initialise and start the market data engine
    engine_instance = init_engine(AsyncSessionLocal)
    await engine_instance.start()

    log.info(
        "market_data_service_started",
        version=settings.APP_VERSION,
        env=settings.APP_ENV,
        mode=settings.KITE_MODE,
    )
    yield

    # Graceful shutdown
    await engine_instance.stop()
    await engine.dispose()
    await close_redis()
    log.info("market_data_service_stopped")


def create_app() -> FastAPI:
    app = FastAPI(
        title="SG Market Data Service",
        description="Real-time and historical market data for NSE equities (SG Trading Platform)",
        version=settings.APP_VERSION,
        docs_url="/docs" if settings.APP_ENV != "production" else None,
        redoc_url=None,
        openapi_url="/openapi.json" if settings.APP_ENV != "production" else None,
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=[os.getenv("ALLOWED_ORIGINS", "http://localhost")],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(api_router)

    @app.get("/health", include_in_schema=False)
    async def health():
        return {"status": "ok", "service": "market-data", "version": settings.APP_VERSION}

    @app.get("/ready", include_in_schema=False)
    async def ready():
        from sqlalchemy import text
        try:
            async with AsyncSessionLocal() as s:
                await s.execute(text("SELECT 1"))
            r = await get_redis()
            await r.ping()
            eng = get_engine()
            return {"status": "ready", "feed": eng.get_stats()}
        except Exception as e:
            return JSONResponse(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                content={"status": "not_ready", "error": str(e)},
            )

    @app.exception_handler(Exception)
    async def unhandled(request: Request, exc: Exception):
        log.error("unhandled_exception", path=request.url.path, error=str(exc), exc_info=True)
        return JSONResponse(
            status_code=500,
            content={"detail": "Internal server error"},
        )

    if settings.PROMETHEUS_ENABLED:
        Instrumentator().instrument(app).expose(app, endpoint="/metrics", include_in_schema=False)

    return app


app = create_app()
