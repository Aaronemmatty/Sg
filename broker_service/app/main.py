"""FastAPI application factory — Broker Service."""
from __future__ import annotations
import os
from contextlib import asynccontextmanager
from collections.abc import AsyncGenerator
from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from prometheus_fastapi_instrumentator import Instrumentator
from app.api.v1.router import api_router
from app.brokers.factory import init_broker, shutdown_broker
from app.core.config import get_settings
from app.core.logging import configure_logging, get_logger
from app.core.redis import close_redis, get_redis

settings = get_settings()
log = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    configure_logging()
    await get_redis()
    await init_broker()
    log.info("broker_service_started", mode=settings.BROKER_MODE, version=settings.APP_VERSION)
    yield
    await shutdown_broker()
    await close_redis()
    log.info("broker_service_stopped")


def create_app() -> FastAPI:
    app = FastAPI(
        title="SG Broker Service",
        description="Broker abstraction layer — Zerodha Kite + Paper trading (SG Trading Platform)",
        version=settings.APP_VERSION,
        docs_url="/docs" if settings.APP_ENV != "production" else None,
        redoc_url=None,
        openapi_url="/openapi.json" if settings.APP_ENV != "production" else None,
        lifespan=lifespan,
    )
    app.add_middleware(CORSMiddleware, allow_origins=[os.getenv("ALLOWED_ORIGINS", "http://localhost")], allow_credentials=True,
                       allow_methods=["*"], allow_headers=["*"])
    app.include_router(api_router)

    @app.get("/health", include_in_schema=False)
    async def health():
        return {"status": "ok", "service": "broker", "mode": settings.BROKER_MODE}

    @app.get("/ready", include_in_schema=False)
    async def ready():
        try:
            r = await get_redis()
            await r.ping()
            from app.brokers.factory import get_broker
            broker = await get_broker()
            return {"status": "ready", "broker": broker.broker_name, "connected": broker.is_connected}
        except Exception as e:
            return JSONResponse(status_code=503, content={"status": "not_ready", "error": str(e)})

    @app.exception_handler(Exception)
    async def unhandled(request: Request, exc: Exception):
        log.error("unhandled_exception", path=request.url.path, error=str(exc), exc_info=True)
        return JSONResponse(status_code=500, content={"detail": "Internal server error"})

    if settings.PROMETHEUS_ENABLED:
        Instrumentator().instrument(app).expose(app, endpoint="/metrics", include_in_schema=False)

    return app


app = create_app()
