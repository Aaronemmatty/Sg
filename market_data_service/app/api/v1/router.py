"""v1 API router."""
from fastapi import APIRouter
from app.api.v1.endpoints.market import router as market_router
from app.api.v1.endpoints.ws import router as ws_router

api_router = APIRouter(prefix="/v1")
api_router.include_router(market_router)
api_router.include_router(ws_router)
