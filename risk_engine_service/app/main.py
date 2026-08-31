from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from prometheus_fastapi_instrumentator import Instrumentator

from app.api import router as risk_router
from app.circuit_breaker import CircuitBreakerRegistry
from app.clients import BrokerServiceClient, MarketDataClient, PortfolioClient
from app.config import get_settings
from app.consumer import IntentConsumer
from app.evaluator import RiskEvaluator
from app.kill_switch import KillSwitch
from app.logging_setup import configure_logging, get_logger
from app.redis_bus import RedisBus
from app.repository import Database
from app.telemetry import configure_tracing

settings = get_settings()
configure_logging(settings.service_name, settings.env)
log = get_logger(module="main")


@asynccontextmanager
async def lifespan(app: FastAPI):
    db = Database(settings.postgres_dsn)
    await db.connect()

    redis_bus = RedisBus(settings.redis_url)
    await redis_bus.connect()

    broker_client = BrokerServiceClient(
        settings.broker_service_url, redis_bus, settings.margin_check_mode, settings.margin_cache_ttl_seconds
    )
    market_data_client = MarketDataClient(settings.market_data_service_url, redis_bus)
    portfolio_client = PortfolioClient(redis_bus, settings.broker_service_url)

    kill_switch = KillSwitch(redis_bus, db, settings.kill_switch_auto_reset_requires_role)
    await kill_switch.load()

    circuit_breakers = CircuitBreakerRegistry(redis_bus, db)

    evaluator = RiskEvaluator(
        db=db,
        broker_client=broker_client,
        market_data_client=market_data_client,
        portfolio_client=portfolio_client,
        kill_switch=kill_switch,
        circuit_breakers=circuit_breakers,
        settings=settings,
    )

    consumer = IntentConsumer(redis_bus, evaluator, db, settings)
    consumer.start()

    app.state.db = db
    app.state.redis_bus = redis_bus
    app.state.broker_client = broker_client
    app.state.market_data_client = market_data_client
    app.state.portfolio_client = portfolio_client
    app.state.kill_switch = kill_switch
    app.state.circuit_breakers = circuit_breakers
    app.state.evaluator = evaluator
    app.state.consumer = consumer

    log.info("risk_engine_service_started", port=settings.service_port)
    try:
        yield
    finally:
        await consumer.stop()
        await broker_client.aclose()
        await market_data_client.aclose()
        await portfolio_client.aclose()
        await redis_bus.disconnect()
        await db.disconnect()
        log.info("risk_engine_service_stopped")


app = FastAPI(
    title="SG Trading Platform - Risk Management Engine",
    version="1.0.0",
    lifespan=lifespan,
)

app.include_router(risk_router, tags=["risk"])

Instrumentator().instrument(app).expose(app, endpoint="/metrics")
configure_tracing(app, settings.otel_service_name, settings.otel_exporter_otlp_endpoint)


@app.get("/health")
async def health():
    return {"status": "ok", "service": settings.service_name}


@app.get("/health/ready")
async def readiness():
    db_ok = app.state.db.pool is not None
    redis_ok = app.state.redis_bus.client is not None
    ok = db_ok and redis_ok
    return {
        "status": "ok" if ok else "degraded",
        "db_connected": db_ok,
        "redis_connected": redis_ok,
        "kill_switch_state": app.state.kill_switch.state.value,
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app.main:app", host="0.0.0.0", port=settings.service_port, log_config=None)
