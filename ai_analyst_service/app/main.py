from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from prometheus_fastapi_instrumentator import Instrumentator

from app.api.v1.router import api_router
from app.clients.execution_client import ExecutionClient
from app.clients.market_data_client import MarketDataClient
from app.clients.portfolio_client import PortfolioClient
from app.clients.risk_client import RiskClient
from app.core.config import settings
from app.core.logging import log
from app.core.redis import close_redis, get_redis
from app.core.tracing import configure_tracing
from app.db.repository import AnalystRepository
from app.db.session import close_pool, init_pool, run_migrations
from app.llm.factory import close_llm_provider, get_llm_provider
from app.services.analysis_service import AnalysisService
from app.services.cache_service import AnalysisCache
from app.services.prompt_manager import PromptManager
from app.services.rate_limiter import RateLimiter


@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info("service_starting", service=settings.service_name, port=settings.port)

    pool = await init_pool()
    app.state.db_pool = pool
    await run_migrations()

    redis_client = get_redis()

    repo = AnalystRepository(pool)
    app.state.repo = repo

    prompt_manager = PromptManager(repo)
    app.state.prompt_manager = prompt_manager

    cache = AnalysisCache(redis_client)
    rate_limiter = RateLimiter(redis_client)
    llm_provider = get_llm_provider()

    portfolio_client = PortfolioClient()
    risk_client = RiskClient()
    execution_client = ExecutionClient()
    market_data_client = MarketDataClient()
    app.state.portfolio_client = portfolio_client
    app.state.risk_client = risk_client
    app.state.execution_client = execution_client
    app.state.market_data_client = market_data_client

    app.state.analysis_service = AnalysisService(
        repo=repo,
        prompt_manager=prompt_manager,
        cache=cache,
        rate_limiter=rate_limiter,
        llm_provider=llm_provider,
    )

    configure_tracing(app)

    log.info("service_started")
    try:
        yield
    finally:
        log.info("service_stopping")
        await portfolio_client.aclose()
        await risk_client.aclose()
        await execution_client.aclose()
        await market_data_client.aclose()
        await close_llm_provider()
        await close_redis()
        await close_pool()
        log.info("service_stopped")


app = FastAPI(
    title="AI Trade Analysis Service",
    description=(
        "LLM-backed explanations of trades, portfolio state, risk posture, "
        "market activity, and performance — read-only aggregation over the "
        "platform's other services plus a provider-agnostic LLM abstraction "
        "layer, prompt management, caching, and rate limiting."
    ),
    version="0.1.0",
    lifespan=lifespan,
)

Instrumentator().instrument(app).expose(app, endpoint="/metrics", include_in_schema=False)

app.include_router(api_router)


@app.get("/", include_in_schema=False)
async def root() -> dict:
    return {"service": settings.service_name, "status": "running"}
