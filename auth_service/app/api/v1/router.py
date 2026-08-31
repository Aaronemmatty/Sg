"""v1 router — aggregates all endpoint routers."""

from fastapi import APIRouter

from app.api.v1.endpoints.auth import router as auth_router
from app.api.v1.endpoints.sessions import router as sessions_router
from app.api.v1.endpoints.api_keys import router as api_keys_router

api_router = APIRouter(prefix="/v1")
api_router.include_router(auth_router)
api_router.include_router(sessions_router)
api_router.include_router(api_keys_router)
