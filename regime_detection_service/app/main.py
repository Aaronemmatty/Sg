"""
regime_detection_service entrypoint.

Wires up: structlog JSON logging, Prometheus /metrics, /health, /ready, the Redis
client, the hybrid classifier, the detection engine, the event-driven candle consumer,
and the watchdog scheduler — matching the conventions of the other platform services.
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI, Request
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest
from sqlalchemy import text
from starlette.responses import Response

from app.api.v1 import regime as regime_routes
from app.api.v1 import websocket as websocket_routes
from app.api.v1.schemas import HealthResponse, ReadyResponse
from app.config import get_settings
from app.core.classifier import HybridClassifier
from app.core.engine import RegimeDetectionEngine
from app.db.session import engine as db_engine
from app.db.session import session_scope
from app.services.candle_consumer import CandleConsumer
from app.services.redis_client import RegimeRedisClient
from app.workers.scheduler import RegimeWatchdogScheduler

settings = get_settings()

# --- Structured JSON logging, matching platform convention --------------------------
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

# --- Prometheus metrics --------------------------------------------------------------
REGIME_RECALC_COUNTER = Counter(
    "regime_recalculations_total", "Total regime recalculations", ["symbol", "timeframe", "outcome"]
)
REGIME_TRANSITION_COUNTER = Counter(
    "regime_transitions_total", "Total confirmed regime transitions", ["symbol", "to_regime"]
)
REQUEST_LATENCY = Histogram(
    "regime_request_latency_seconds", "Request latency", ["method", "path"]
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("starting regime_detection_service")

    redis_client = RegimeRedisClient(settings)
    await redis_client.connect()

    classifier = HybridClassifier(
        model_path=settings.REGIME_MODEL_PATH, min_ml_confidence=0.45
    )
    detection_engine = RegimeDetectionEngine(settings, redis_client, classifier)

    app.state.redis_client = redis_client
    app.state.classifier = classifier
    app.state.engine = detection_engine
    app.state.metrics = {
        "recalc_counter": REGIME_RECALC_COUNTER,
        "transition_counter": REGIME_TRANSITION_COUNTER,
    }

    candle_consumer = CandleConsumer(settings, redis_client, detection_engine)
    watchdog = RegimeWatchdogScheduler(settings, redis_client, detection_engine)
    await candle_consumer.start()
    await watchdog.start()
    app.state.candle_consumer = candle_consumer
    app.state.watchdog = watchdog

    logger.info(
        "regime_detection_service ready",
        ml_model_loaded=classifier.is_using_ml,
        primary_symbol=settings.PRIMARY_SYMBOL,
        watchlist_size=len(settings.WATCHLIST_SYMBOLS),
    )

    yield

    logger.info("shutting down regime_detection_service")
    await candle_consumer.stop()
    await watchdog.stop()
    await redis_client.close()
    await db_engine.dispose()


app = FastAPI(
    title="regime_detection_service",
    description="Market Regime Detection Engine — SG Trading Platform",
    version="1.0.0",
    lifespan=lifespan,
)

app.include_router(regime_routes.router)
app.include_router(regime_routes.backtest_router)
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

    classifier_loaded = bool(getattr(request.app.state, "classifier", None) and request.app.state.classifier.is_using_ml)

    status_str = "ok" if db_ok and redis_ok else "degraded"
    return ReadyResponse(status=status_str, database=db_ok, redis=redis_ok, classifier_loaded=classifier_loaded)


@app.get("/metrics", tags=["ops"])
async def metrics() -> Response:
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
