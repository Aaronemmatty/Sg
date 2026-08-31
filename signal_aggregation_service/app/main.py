"""
signal_aggregation_service entrypoint.

Wires up: structlog JSON logging, Prometheus /metrics, /health, /ready, the Redis
client, the weight store, the aggregation engine, the event-driven signal/regime
consumer, and the watchdog scheduler — matching the conventions of the other platform
services (see regime_detection_service/app/main.py for the identical pattern).
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI, Request
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest
from sqlalchemy import text
from starlette.responses import Response

from app.api.v1 import aggregation as aggregation_routes
from app.api.v1 import websocket as websocket_routes
from app.api.v1.schemas import HealthResponse, ReadyResponse
from app.config import get_settings
from app.core.engine import SignalAggregationEngine
from app.db.session import engine as db_engine
from app.db.session import session_scope
from app.services.redis_client import AggregationRedisClient
from app.services.signal_consumer import SignalConsumer
from app.services.weight_store import WeightStore
from app.services.weights_cache_invalidator import WeightsCacheInvalidator
from app.workers.scheduler import AggregationWatchdogScheduler

settings = get_settings()

structlog.configure(
    processors=[
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.JSONRenderer(),
    ],
    wrapper_class=structlog.make_filtering_bound_logger(getattr(logging, settings.LOG_LEVEL.upper())),
    logger_factory=structlog.PrintLoggerFactory(),
)
logging.basicConfig(level=settings.LOG_LEVEL)
logger = structlog.get_logger(service=settings.SERVICE_NAME)

AGGREGATIONS_COUNTER = Counter(
    "signal_aggregations_total", "Total aggregation runs", ["symbol", "timeframe", "final_signal"]
)
REQUEST_LATENCY = Histogram(
    "signal_aggregation_request_latency_seconds", "Request latency", ["method", "path"]
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("starting signal_aggregation_service")

    redis_client = AggregationRedisClient(settings)
    await redis_client.connect()

    weight_store = WeightStore(settings)
    aggregation_engine = SignalAggregationEngine(settings, redis_client, weight_store)

    app.state.redis_client = redis_client
    app.state.weight_store = weight_store
    app.state.engine = aggregation_engine
    app.state.metrics = {"aggregations_counter": AGGREGATIONS_COUNTER}

    signal_consumer = SignalConsumer(settings, redis_client, aggregation_engine)
    watchdog = AggregationWatchdogScheduler(settings, redis_client, aggregation_engine)
    cache_invalidator = WeightsCacheInvalidator(redis_client, weight_store)
    await signal_consumer.start()
    await watchdog.start()
    await cache_invalidator.start()
    app.state.signal_consumer = signal_consumer
    app.state.watchdog = watchdog
    app.state.cache_invalidator = cache_invalidator

    logger.info(
        "signal_aggregation_service ready",
        primary_symbol=settings.PRIMARY_SYMBOL,
        watchlist_size=len(settings.WATCHLIST_SYMBOLS),
        strategy_registry=settings.STRATEGY_REGISTRY,
    )

    yield

    logger.info("shutting down signal_aggregation_service")
    await signal_consumer.stop()
    await watchdog.stop()
    await cache_invalidator.stop()
    await redis_client.close()
    await db_engine.dispose()


app = FastAPI(
    title="signal_aggregation_service",
    description="Signal Aggregation Engine — SG Trading Platform",
    version="1.0.0",
    lifespan=lifespan,
)

app.include_router(aggregation_routes.router)
app.include_router(aggregation_routes.weights_router)
app.include_router(websocket_routes.router)


@app.middleware("http")
async def add_request_logging(request: Request, call_next):
    with REQUEST_LATENCY.labels(method=request.method, path=request.url.path).time():
        response = await call_next(request)
    return response


@app.get("/health", response_model=HealthResponse, tags=["ops"])
async def health() -> HealthResponse:
    return HealthResponse(status="ok", service=settings.SERVICE_NAME)


@app.get("/ready", response_model=ReadyResponse, tags=["ops"])
async def ready(request: Request) -> ReadyResponse:
    db_ok = True
    try:
        async with session_scope() as session:
            await session.execute(text("SELECT 1"))
    except Exception:  # noqa: BLE001
        db_ok = False

    redis_ok = True
    try:
        await request.app.state.redis_client.client.ping()
    except Exception:  # noqa: BLE001
        redis_ok = False

    status_str = "ok" if db_ok and redis_ok else "degraded"
    return ReadyResponse(status=status_str, database=db_ok, redis=redis_ok)


@app.get("/metrics", tags=["ops"])
async def metrics() -> Response:
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
