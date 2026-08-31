from fastapi import APIRouter

from app.api.v1.endpoints import health, ledger, performance, portfolio, stream

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(health.router)
api_router.include_router(portfolio.router)
api_router.include_router(performance.router)
api_router.include_router(ledger.router)
api_router.include_router(stream.router)
