from __future__ import annotations

from fastapi import APIRouter, Request

from app.core.config import settings

router = APIRouter(tags=["health"])


@router.get("/health")
async def health(request: Request) -> dict:
    pool = getattr(request.app.state, "db_pool", None)
    db_ok = False
    if pool is not None:
        try:
            async with pool.acquire() as conn:
                await conn.fetchval("SELECT 1")
            db_ok = True
        except Exception:  # noqa: BLE001
            db_ok = False

    llm_configured = bool(settings.anthropic_api_key) if settings.llm_provider == "anthropic" else True

    return {
        "status": "ok" if db_ok else "degraded",
        "service": "ai_analyst_service",
        "db": "ok" if db_ok else "unreachable",
        "llm_provider": settings.llm_provider,
        "llm_configured": llm_configured,
    }
