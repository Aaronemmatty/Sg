from __future__ import annotations

from fastapi import APIRouter, Request

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

    return {
        "status": "ok" if db_ok else "degraded",
        "service": "backtesting_engine_service",
        "db": "ok" if db_ok else "unreachable",
    }
