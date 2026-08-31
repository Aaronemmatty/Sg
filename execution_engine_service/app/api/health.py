from fastapi import APIRouter
from fastapi.responses import JSONResponse

from app import db

router = APIRouter(tags=["health"])


@router.get("/health")
async def health():
    return {"status": "ok", "service": "execution_engine_service"}


@router.get("/ready")
async def ready():
    if db.pool is None:
        return JSONResponse(status_code=503, content={"status": "not_ready", "reason": "db_pool_not_initialized"})
    try:
        async with db.pool.acquire() as conn:
            await conn.fetchval("SELECT 1")
    except Exception as exc:
        return JSONResponse(status_code=503, content={"status": "not_ready", "reason": str(exc)})
    return {"status": "ready"}
