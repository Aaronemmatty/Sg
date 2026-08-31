"""Health and config endpoints."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from app.auth import get_current_user
from app.core.config import get_settings
from app.core.redis import get_redis
from app.db.session import AsyncSessionLocal
from app.schemas.api import HealthResponse, OrchestratorConfigResponse, ReadyResponse
from app.utils.app_state import get_consumer

settings = get_settings()
router = APIRouter(tags=["ops"])


@router.get("/health", response_model=HealthResponse, include_in_schema=False)
async def health():
    return HealthResponse(
        status="ok",
        service="execution-orchestrator",
        version=settings.APP_VERSION,
        environment=settings.APP_ENV,
    )


@router.get("/ready", include_in_schema=False)
async def ready():
    redis_ok = False
    db_ok = False

    try:
        r = await get_redis()
        await r.ping()
        redis_ok = True
    except Exception:
        pass

    try:
        async with AsyncSessionLocal() as session:
            from sqlalchemy import text
            await session.execute(text("SELECT 1"))
        db_ok = True
    except Exception:
        pass

    consumer = get_consumer()
    consumer_running = consumer is not None and consumer.is_running

    # Try to get open intents count
    open_intents = 0
    try:
        async with AsyncSessionLocal() as session:
            from app.db.repository import IntentRepository
            repo = IntentRepository(session)
            open_intents = await repo.count_open_intents()
    except Exception:
        pass

    all_ok = redis_ok and db_ok
    content = ReadyResponse(
        status="ready" if all_ok else "degraded",
        redis=redis_ok,
        database=db_ok,
        consumer_running=consumer_running,
        open_intents=open_intents,
    )

    return JSONResponse(
        status_code=200 if all_ok else 503,
        content=content.model_dump(),
    )


@router.get("/api/v1/config", response_model=OrchestratorConfigResponse, tags=["config"])
async def get_config(_user = Depends(get_current_user)):
    """Return current orchestrator thresholds (read-only)."""
    return OrchestratorConfigResponse(
        min_confidence=settings.MIN_CONFIDENCE,
        min_liquidity_value_inr=settings.MIN_LIQUIDITY_VALUE_INR,
        max_position_pct=settings.MAX_POSITION_PCT,
        max_sector_exposure_pct=settings.MAX_SECTOR_EXPOSURE_PCT,
        max_correlation_score=settings.MAX_CORRELATION_SCORE,
        default_risk_pct=settings.DEFAULT_RISK_PCT,
        max_allocation_inr=settings.MAX_ALLOCATION_INR,
        min_allocation_inr=settings.MIN_ALLOCATION_INR,
        daily_loss_limit_inr=settings.DAILY_LOSS_LIMIT_INR,
        daily_loss_limit_pct=settings.DAILY_LOSS_LIMIT_PCT,
        max_portfolio_drawdown_pct=settings.MAX_PORTFOLIO_DRAWDOWN_PCT,
        max_open_intents=settings.MAX_OPEN_INTENTS,
    )
