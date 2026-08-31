"""Health check endpoint — matches the pattern from 8001–8008."""
from __future__ import annotations

from fastapi import APIRouter

from app.core.config import settings
from app.core.logging import get_logger
from app.db.session import get_pool

log = get_logger(__name__)
router = APIRouter(tags=["health"])


@router.get("/health")
async def health():
    db_ok = False
    try:
        async with get_pool().acquire() as conn:
            await conn.fetchval("SELECT 1")
        db_ok = True
    except Exception:
        log.warning("health_check_db_failed")

    status = "ok" if db_ok else "degraded"
    return {
        "status": status,
        "service": settings.service_name,
        "port": settings.service_port,
        "env": settings.env,
        "db": "ok" if db_ok else "error",
    }


@router.get("/")
async def root():
    return {"service": settings.service_name, "version": "0.1.0"}
