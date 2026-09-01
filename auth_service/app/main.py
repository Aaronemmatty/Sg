"""FastAPI application factory."""

from __future__ import annotations

from contextlib import asynccontextmanager
from collections.abc import AsyncGenerator

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from prometheus_fastapi_instrumentator import Instrumentator

from app.api.v1.router import api_router
from app.core.config import get_settings
from app.core.logging import configure_logging, get_logger
from app.core.redis import close_redis, get_redis
from app.db.session import engine
from app.middleware.security import (
    CorrelationIDMiddleware,
    RequestLoggingMiddleware,
    SecurityHeadersMiddleware,
)

settings = get_settings()
log = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    configure_logging()
    # Warm-up
    await get_redis()
    log.info("auth_service_started", version=settings.APP_VERSION, env=settings.APP_ENV)
    yield
    # Shutdown
    await engine.dispose()
    await close_redis()
    log.info("auth_service_stopped")


def create_app() -> FastAPI:
    app = FastAPI(
        title="SG Auth Service",
        description="Authentication & Identity microservice for the SG Trading Platform",
        version=settings.APP_VERSION,
        docs_url="/docs" if settings.APP_ENV != "production" else None,
        redoc_url="/redoc" if settings.APP_ENV != "production" else None,
        openapi_url="/openapi.json" if settings.APP_ENV != "production" else None,
        lifespan=lifespan,
        root_path=settings.ROOT_PATH,
    )

    # ── Middleware (order matters: outermost first) ───────────────────────────
    app.add_middleware(CorrelationIDMiddleware)
    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(RequestLoggingMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[str(o) for o in settings.ALLOWED_ORIGINS],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["X-Correlation-ID"],
    )

    # ── Routes ────────────────────────────────────────────────────────────────
    app.include_router(api_router)
    app.include_router(api_router, prefix="/api")

    # ── Health / readiness ────────────────────────────────────────────────────
    @app.get("/health", tags=["Ops"], include_in_schema=False)
    async def health() -> dict:
        return {"status": "ok", "service": "auth", "version": settings.APP_VERSION}

    @app.get("/ready", tags=["Ops"], include_in_schema=False)
    async def ready() -> dict:
        from sqlalchemy import text
        from app.db.session import AsyncSessionLocal
        try:
            async with AsyncSessionLocal() as s:
                await s.execute(text("SELECT 1"))
            redis = await get_redis()
            await redis.ping()
            return {"status": "ready"}
        except Exception as e:
            return JSONResponse(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                content={"status": "not_ready", "error": str(e)},
            )

    # ── Exception handlers ────────────────────────────────────────────────────
    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(request: Request, exc: RequestValidationError):
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content={"detail": exc.errors(), "code": "validation_error"},
        )

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception):
        log.error("unhandled_exception", error=str(exc), path=request.url.path, exc_info=True)
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"detail": "Internal server error", "code": "internal_error"},
        )

    # ── Prometheus ────────────────────────────────────────────────────────────
    if settings.PROMETHEUS_ENABLED:
        Instrumentator().instrument(app).expose(app, endpoint="/metrics", include_in_schema=False)

    return app


app = create_app()
