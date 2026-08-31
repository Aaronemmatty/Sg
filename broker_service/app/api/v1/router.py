"""v1 router."""
from fastapi import APIRouter
from app.api.v1.endpoints.broker import router as broker_router

api_router = APIRouter(prefix="/v1")
api_router.include_router(broker_router)
