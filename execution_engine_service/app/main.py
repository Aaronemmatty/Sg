"""
execution_engine_service (8008) — FastAPI app.

Lifespan responsibilities:
  - open DB pool, run migrations
  - connect Redis
  - register event_bus subscribers (outbound Redis publish, metrics already
    self-registering via prometheus_client)
  - start background tasks: execution worker (consumes sg:risk_approved:*),
    reconciliation loop, held-intent sweeper
  - graceful shutdown of all of the above
"""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from prometheus_fastapi_instrumentator import Instrumentator

from app import db, hold_manager
from app.api import health, orders, stream
from app.clients import broker_client
from app.config import settings
from app.events import event_bus
from app.logging_config import configure_logging, get_logger
from app.market_data_client import market_data_client
from app.redis_bus import redis_bus
from app.reconciliation import reconciliation_loop
from app.worker import ExecutionWorker

configure_logging()
log = get_logger(__name__)

_stop_event = asyncio.Event()
_background_tasks: list[asyncio.Task] = []


def _configure_tracing(app: FastAPI) -> None:
    resource = Resource.create({"service.name": settings.service_name})
    provider = TracerProvider(resource=resource)
    provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=settings.otel_exporter_otlp_endpoint)))
    trace.set_tracer_provider(provider)
    FastAPIInstrumentor.instrument_app(app)
    HTTPXClientInstrumentor().instrument()


async def _held_intent_sweeper() -> None:
    log.info("held_intent_sweeper_started", interval_s=settings.hold_sweep_interval_seconds)
    while not _stop_event.is_set():
        try:
            count = await hold_manager.sweep_expired_holds()
            if count:
                log.info("held_intents_swept", count=count)
        except Exception:
            log.exception("held_intent_sweep_failed")
        try:
            await asyncio.wait_for(_stop_event.wait(), timeout=settings.hold_sweep_interval_seconds)
        except asyncio.TimeoutError:
            pass
    log.info("held_intent_sweeper_stopped")


async def _publish_to_redis(event) -> None:
    """event_bus subscriber: forwards every order-lifecycle event to
    sg:executions:{symbol} (for portfolio_management_service) and to the
    general sg:execution:events bus (for SSE/dashboard consumers)."""
    await redis_bus.publish_execution_event(event)
    await redis_bus.publish_general_event(event)


@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info("execution_engine_starting", env=settings.env, port=settings.service_port)

    await db.init_pool()
    await redis_bus.connect()

    event_bus.subscribe(_publish_to_redis)

    worker = ExecutionWorker(redis_bus, broker_client, market_data_client)

    worker_task = asyncio.create_task(worker.run(_stop_event))
    reconciliation_task = asyncio.create_task(reconciliation_loop(broker_client, _stop_event))
    sweeper_task = asyncio.create_task(_held_intent_sweeper())
    _background_tasks.extend([worker_task, reconciliation_task, sweeper_task])

    log.info("execution_engine_started")
    try:
        yield
    finally:
        log.info("execution_engine_stopping")
        _stop_event.set()
        await worker.shutdown()
        for task in _background_tasks:
            task.cancel()
        await asyncio.gather(*_background_tasks, return_exceptions=True)
        await broker_client.aclose()
        await market_data_client.aclose()
        await redis_bus.close()
        await db.close_pool()
        log.info("execution_engine_stopped")


app = FastAPI(title="execution_engine_service", version="0.1.0", lifespan=lifespan)

app.include_router(health.router)
app.include_router(orders.router)
app.include_router(stream.router)

Instrumentator().instrument(app).expose(app, endpoint="/metrics")

# OTel tracing is wired unconditionally (matches the convention used by
# 8001-8007); point OTEL_EXPORTER_OTLP_ENDPOINT at a local collector in dev.
try:
    _configure_tracing(app)
except Exception:
    log.warning("otel_tracing_setup_failed_continuing_without_tracing")
