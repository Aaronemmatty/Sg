"""API v1 router."""
from fastapi import APIRouter
from app.api.v1.endpoints import health, intents

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(intents.router, prefix="/api/v1")
