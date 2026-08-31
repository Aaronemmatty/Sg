"""v1 router."""
from fastapi import APIRouter
from app.api.v1.endpoints.strategy import router as strategy_router
api_router = APIRouter(prefix="/v1")
api_router.include_router(strategy_router)
