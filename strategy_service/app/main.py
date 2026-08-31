"""FastAPI application factory — Strategy Service."""
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
from app.db.session import engine, AsyncSessionLocal
from app.lifecycle.manager import get_lifecycle_manager
from app.lifecycle.watcher import HotReloadWatcher
from app.registry.registry import get_loader

settings = get_settings()
log = get_logger(__name__)
_watcher = HotReloadWatcher()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    configure_logging()
    await get_redis()
    loader = get_loader()
    await loader.load_builtins()
    await loader.load_directory(settings.USER_STRATEGIES_DIR)
    await _watcher.start()
    log.info("strategy_service_started", version=settings.APP_VERSION,
             env=settings.APP_ENV, mode=settings.TRADING_MODE)
    yield
    await get_lifecycle_manager().stop_all()
    await _watcher.stop()
    await engine.dispose()
    await close_redis()
    log.info("strategy_service_stopped")


def create_app() -> FastAPI:
    app = FastAPI(
        title="SG Strategy Service",
        description="Strategy Core Framework — NSE equities (SG Trading Platform)",
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
        from app.registry.registry import get_registry
        return {"status": "ok", "service": "strategy",
                "strategies": get_registry().count,
                "instances": len(get_lifecycle_manager().list_instances())}

    @app.get("/ready", include_in_schema=False)
    async def ready():
        try:
            r = await get_redis(); await r.ping()
            return {"status": "ready"}
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
